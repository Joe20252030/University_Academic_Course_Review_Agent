from __future__ import annotations

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
    # Validate files exist, fall back to generic
    if not (_PROMPTS_DIR / planner_file).exists():
        planner_file = "planner.md"
    if not (_PROMPTS_DIR / writer_file).exists():
        writer_file = "reviewer.md"
    return planner_file, writer_file


# ---------------------------------------------------------------------------
# Pipeline functions
# ---------------------------------------------------------------------------

def build_outline(chunks: list[Document]) -> str:
    outline = ""
    for chunk in chunks:
        outline += chunk.page_content + "\n\n"
    return outline.strip()


def generate_plan(
    docs: list[Document],
    user_prefs: dict,
    llm_client: LLMClient,
) -> ReviewPlan:
    structured_llm = llm_client.with_structured_output(ReviewPlan)

    outline_text = "\n".join(d.page_content[:500] for d in docs[:5])

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

    task_type = TaskType(user_prefs.get("task_type", "review_summary"))
    _, writer_file = _get_prompt_files(task_type)
    prompt = ChatPromptTemplate.from_template(load_prompt(writer_file))

    resp = llm_client.invoke(
        prompt.format_messages(
            title=section.title,
            context=context,
            exam_type=user_prefs.get("exam_type", "other"),
            exam_format=user_prefs.get("exam_format", "unknown"),
        )
    )
    return getattr(resp, "content", str(resp))


def assemble_markdown(plan: ReviewPlan, sections: list[str], task_type: str = "review_summary") -> str:
    try:
        tt = TaskType(task_type)
    except ValueError:
        tt = TaskType.review_summary
    title_suffix = _TASK_TITLES.get(tt, "Review")
    md = f"# {plan.course_title} - {title_suffix}\n\n"
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
        exam_type: str = "other",
        task_type: str = "review_summary",
        extra_instructions: str = "",
        workspace_id: str = "default",
        copy_to_workspace: bool = True,
    ) -> tuple[ReviewPlan, str, str]:
        """Run the full RAG pipeline with classified documents.

        Args:
            classified_files: Mapping of DocumentType to list of file paths
            exam_format: The exam format (written, mcq, mixed, unknown)
            exam_type: The exam type (quiz, midterm, final, term_test, other)
            task_type: What to generate (review_summary, practice_booklet,
                       mock_exam, exam_prediction)
            extra_instructions: Optional user-provided extra instructions
            workspace_id: Workspace identifier
            copy_to_workspace: Whether to copy files to classified workspace folders

        Returns:
            Tuple of (ReviewPlan, markdown content, markdown file path)
        """
        ws = workspace_paths(self.settings.workspace_root, workspace_id)
        ensure_workspace_dirs(ws)

        # Load and split documents with type-specific strategies
        chunks = self.loader.load_and_split_classified(
            classified_files,
            workspace_paths=ws if copy_to_workspace else None,
        )

        if not chunks:
            raise LLMError("No document chunks were created. Please check your input files.")

        # Build vector store and retriever
        vectorstore = get_or_create_vectorstore(chunks, self.settings, ws)
        retriever = build_retriever(vectorstore, self.settings)

        # Load raw documents for plan generation (need full context)
        all_docs: list[Document] = []
        for paths in classified_files.values():
            all_docs.extend(self.loader.load_documents(paths))

        # Build user prefs dict shared by planner and writer
        user_prefs = {
            "exam_format": exam_format,
            "exam_type": exam_type,
            "task_type": task_type,
            "extra_instructions": extra_instructions,
        }

        # Generate plan
        plan = generate_plan(all_docs, user_prefs, self.llm_client)

        if not plan.sections:
            raise LLMError("Generated an empty plan (no sections). Try again or adjust the prompt.")

        # Write each section
        section_texts: list[str] = []
        for section in plan.sections:
            section_texts.append(write_section(section, retriever, self.llm_client, user_prefs))

        # Assemble and save
        final_md = assemble_markdown(plan, section_texts, task_type)
        md_path = save_markdown(final_md, ws)
        return plan, final_md, md_path

    def run_simple(
        self,
        file_paths: list[str],
        exam_format: str,
        exam_type: str = "other",
        task_type: str = "review_summary",
        extra_instructions: str = "",
        workspace_id: str = "default",
    ) -> tuple[ReviewPlan, str, str]:
        """Simplified run method that treats all files as 'other' type."""
        classified_files = {DocumentType.other: file_paths}
        return self.run_end_to_end(
            classified_files=classified_files,
            exam_format=exam_format,
            exam_type=exam_type,
            task_type=task_type,
            extra_instructions=extra_instructions,
            workspace_id=workspace_id,
            copy_to_workspace=False,
        )
