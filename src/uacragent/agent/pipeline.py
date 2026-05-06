from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.retrievers import BaseRetriever

from uacragent.export.markdown import save_markdown
from uacragent.domain.models import ReviewPlan, SectionSpec
from uacragent.domain.errors import LLMError
from uacragent.domain.types import DocumentType, TaskType
from uacragent.infra.llm import LLMClient
from uacragent.infra.loaders import DocumentLoader
from uacragent.infra.settings import Settings
from uacragent.infra.vectorstore import build_retriever, get_or_create_vectorstore
from uacragent.infra.workspace import ensure_workspace_dirs, workspace_paths, WorkspacePaths


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------

_PROMPTS_DIR = Path(__file__).parent / "prompts"

# Maps TaskType -> (planner prompt filename, writer prompt filename)
_PROMPT_FILES: dict[TaskType, tuple[str, str]] = {
    TaskType.review_summary: ("review_summary_planner.md", "review_summary_writer.md"),
    TaskType.practice_booklet: ("practice_booklet_planner.md", "practice_booklet_writer.md"),
    TaskType.mock_exam: ("mock_exam_planner.md", "mock_exam_writer.md"),
    TaskType.exam_prediction: ("exam_prediction_planner.md", "exam_prediction_writer.md"),
}

# Human-readable output title per task type
_TASK_TITLES: dict[TaskType, str] = {
    TaskType.review_summary: "Exam Review",
    TaskType.practice_booklet: "Practice Booklet",
    TaskType.mock_exam: "Mock Exam",
    TaskType.exam_prediction: "Exam Prediction",
}


def load_prompt(name: str) -> str:
    prompt_path = _PROMPTS_DIR / name
    return prompt_path.read_text(encoding="utf-8")


def _get_prompt_files(task_type: TaskType) -> tuple[str, str]:
    """Return (planner_file, writer_file) for the given task type.

    Falls back to the generic planner.md / reviewer.md if task-specific
    files don't exist.
    """
    planner_file, writer_file = _PROMPT_FILES.get(
        task_type, ("planner.md", "reviewer.md")
    )
    if not (_PROMPTS_DIR / planner_file).exists():
        planner_file = "planner.md"
    if not (_PROMPTS_DIR / writer_file).exists():
        writer_file = "reviewer.md"
    return planner_file, writer_file


# ---------------------------------------------------------------------------
# Pipeline functions
# ---------------------------------------------------------------------------

def build_outline(docs: list[Document], max_docs: int = 20, chars_per_doc: int = 800) -> str:
    """Build a representative outline from documents for plan generation.

    Samples up to `max_docs` documents (evenly spaced if more are available)
    and takes up to `chars_per_doc` characters from each, giving the planner
    a broad view of the course material.
    """
    if not docs:
        return ""

    if len(docs) <= max_docs:
        sampled = docs
    else:
        step = len(docs) / max_docs
        sampled = [docs[int(i * step)] for i in range(max_docs)]

    parts = [d.page_content[:chars_per_doc] for d in sampled]
    return "\n\n".join(parts).strip()


def generate_plan(
    docs: list[Document],
    user_prefs: dict,
    llm_client: LLMClient,
) -> ReviewPlan:
    structured_llm = llm_client.with_structured_output(ReviewPlan)

    outline_text = build_outline(docs)

    task_type = TaskType(user_prefs.get("task_type", "review_summary"))
    planner_file, _ = _get_prompt_files(task_type)
    prompt = ChatPromptTemplate.from_template(load_prompt(planner_file))

    try:
        plan: ReviewPlan = structured_llm.invoke(
            prompt.format_messages(
                outline=outline_text,
                exam_format=user_prefs.get("exam_format", "unknown"),
                exam_type=user_prefs.get("exam_type", "other"),
                extra_instructions=user_prefs.get("extra_instructions", "None"),
                course_name=user_prefs.get("course_name", ""),
                university_name=user_prefs.get("university_name", "") or "Not specified",
                major=user_prefs.get("major", "") or "Not specified",
                course_code=user_prefs.get("course_code", "") or "Not specified",
                professor_name=user_prefs.get("professor_name", "") or "Not specified",
                semester=user_prefs.get("semester", "") or "Not specified",
                exam_duration=user_prefs.get("exam_duration", "") or "Not specified",
                exam_info=user_prefs.get("exam_info", "") or "None provided",
            )
        )
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"Failed to generate plan: {exc}") from exc

    return plan


def write_section(
    section: SectionSpec,
    retriever: BaseRetriever,
    llm_client: LLMClient,
    user_prefs: dict | None = None,
) -> str:
    user_prefs = user_prefs or {}

    query = section.title + " " + " ".join(section.key_topics)
    docs: list[Document] = retriever.invoke(query)
    context = "\n\n".join(d.page_content for d in docs)

    key_topics_text = "\n".join(f"- {t}" for t in section.key_topics)

    task_type = TaskType(user_prefs.get("task_type", "review_summary"))
    _, writer_file = _get_prompt_files(task_type)
    prompt = ChatPromptTemplate.from_template(load_prompt(writer_file))

    resp = llm_client.invoke(
        prompt.format_messages(
            title=section.title,
            key_topics=key_topics_text,
            context=context,
            exam_type=user_prefs.get("exam_type", "other"),
            exam_format=user_prefs.get("exam_format", "unknown"),
            extra_instructions=user_prefs.get("extra_instructions", "") or "None",
            course_name=user_prefs.get("course_name", ""),
            university_name=user_prefs.get("university_name", "") or "Not specified",
            major=user_prefs.get("major", "") or "Not specified",
            course_code=user_prefs.get("course_code", "") or "Not specified",
            professor_name=user_prefs.get("professor_name", "") or "Not specified",
            semester=user_prefs.get("semester", "") or "Not specified",
            exam_duration=user_prefs.get("exam_duration", "") or "Not specified",
            exam_info=user_prefs.get("exam_info", "") or "None provided",
        )
    )
    return getattr(resp, "content", str(resp))


def write_sections_parallel(
    sections: list[SectionSpec],
    retriever: BaseRetriever,
    llm_client: LLMClient,
    user_prefs: dict | None = None,
    max_workers: int = 4,
) -> list[str]:
    """Write all sections concurrently, preserving their original order."""
    results: list[str] = [""] * len(sections)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {
            executor.submit(write_section, section, retriever, llm_client, user_prefs): i
            for i, section in enumerate(sections)
        }
        for future in as_completed(future_to_index):
            idx = future_to_index[future]
            results[idx] = future.result()

    return results


def assemble_markdown(plan: ReviewPlan, sections: list[str], task_type: str = "review_summary") -> str:
    try:
        tt = TaskType(task_type)
    except ValueError:
        tt = TaskType.review_summary
    title_suffix = _TASK_TITLES.get(tt, "Review")

    # Build a rich header using available course info from the plan
    header_lines = [f"# {plan.course_title} - {title_suffix}"]
    meta_parts = []
    if plan.university_name:
        meta_parts.append(f"**University:** {plan.university_name}")
    if plan.major:
        meta_parts.append(f"**Major:** {plan.major}")
    if plan.course_code:
        meta_parts.append(f"**Course:** {plan.course_code}")
    if plan.professor_name:
        meta_parts.append(f"**Professor:** {plan.professor_name}")
    if plan.semester:
        meta_parts.append(f"**Semester:** {plan.semester}")
    if meta_parts:
        header_lines.append("  |  ".join(meta_parts))
    header_lines.append("")

    md = "\n".join(header_lines) + "\n"
    for s in sections:
        md += s + "\n\n"
    return md


# ---------------------------------------------------------------------------
# AgentPipeline
# ---------------------------------------------------------------------------

class AgentPipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.loader = DocumentLoader(settings)
        self.llm_client = LLMClient(settings)

    def run_end_to_end(
        self,
        classified_files: dict[DocumentType, list[str]],
        exam_format: str,
        course_name: str,
        exam_type: str = "other",
        task_type: str = "review_summary",
        extra_instructions: str = "",
        workspace_id: str = "default",
        copy_to_workspace: bool = True,
        university_name: str = "",
        major: str = "",
        course_code: str = "",
        professor_name: str = "",
        semester: str = "",
        exam_duration: str = "",
        exam_info: str = "",
    ) -> tuple[ReviewPlan, str, str]:
        """Run the full RAG pipeline with classified documents.

        Returns:
            Tuple of (ReviewPlan, markdown content, markdown file path)
        """
        ws = workspace_paths(self.settings.workspace_root, workspace_id)
        ensure_workspace_dirs(ws)

        chunks = self.loader.load_and_split_classified(
            classified_files,
            workspace_paths=ws if copy_to_workspace else None,
        )

        if not chunks:
            raise LLMError("No document chunks were created. Please check your input files.")

        vectorstore = get_or_create_vectorstore(chunks, self.settings, ws)
        retriever = build_retriever(vectorstore, self.settings)

        all_docs: list[Document] = []
        for paths in classified_files.values():
            all_docs.extend(self.loader.load_documents(paths))

        user_prefs = {
            "exam_format": exam_format,
            "exam_type": exam_type,
            "task_type": task_type,
            "extra_instructions": extra_instructions,
            "course_name": course_name,
            "university_name": university_name,
            "major": major,
            "course_code": course_code,
            "professor_name": professor_name,
            "semester": semester,
            "exam_duration": exam_duration,
            "exam_info": exam_info,
        }

        plan = generate_plan(all_docs, user_prefs, self.llm_client)

        if not plan.sections:
            raise LLMError("Generated an empty plan (no sections). Try again or adjust the prompt.")

        section_texts = write_sections_parallel(
            plan.sections, retriever, self.llm_client, user_prefs
        )

        final_md = assemble_markdown(plan, section_texts, task_type)
        md_path = save_markdown(final_md, ws)
        return plan, final_md, md_path

    def run_simple(
        self,
        file_paths: list[str],
        exam_format: str,
        course_name: str,
        exam_type: str = "other",
        task_type: str = "review_summary",
        extra_instructions: str = "",
        workspace_id: str = "default",
        university_name: str = "",
        major: str = "",
        course_code: str = "",
        professor_name: str = "",
        semester: str = "",
        exam_duration: str = "",
        exam_info: str = "",
    ) -> tuple[ReviewPlan, str, str]:
        """Simplified run method that treats all files as 'other' type."""
        classified_files = {DocumentType.other: file_paths}
        return self.run_end_to_end(
            classified_files=classified_files,
            exam_format=exam_format,
            course_name=course_name,
            exam_type=exam_type,
            task_type=task_type,
            extra_instructions=extra_instructions,
            workspace_id=workspace_id,
            copy_to_workspace=False,
            university_name=university_name,
            major=major,
            course_code=course_code,
            professor_name=professor_name,
            semester=semester,
            exam_duration=exam_duration,
            exam_info=exam_info,
        )
