from __future__ import annotations

import shutil
import time
from collections.abc import Callable
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
    """Return (planner_file, writer_file) for the given task type."""
    if task_type not in _PROMPT_FILES:
        raise ValueError(f"No prompt files registered for task type: {task_type!r}")
    return _PROMPT_FILES[task_type]


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
    outline_text = build_outline(docs)

    task_type = TaskType(user_prefs.get("task_type", "review_summary"))
    planner_file, _ = _get_prompt_files(task_type)
    prompt = ChatPromptTemplate.from_template(load_prompt(planner_file))

    messages = prompt.format_messages(
        outline=outline_text,
        exam_format=user_prefs.get("exam_format", "unknown"),
        exam_type=user_prefs.get("exam_type", "other"),
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

    plan: ReviewPlan = llm_client.generate_structured(ReviewPlan, messages)
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


def write_sections_sequential(
    sections: list[SectionSpec],
    retriever: BaseRetriever,
    llm_client: LLMClient,
    user_prefs: dict | None = None,
    request_delay: float = 3.0,
    progress_cb: Callable[[str], None] | None = None,
) -> list[str]:
    """Write sections one at a time with a delay between each LLM call.

    Sequential execution guarantees that only one request is in-flight at any
    moment. The delay is inserted *after* each completed call (not before the
    next submission), so it is always respected regardless of how long the
    previous call took.
    """
    results: list[str] = []
    n = len(sections)
    for i, section in enumerate(sections):
        if progress_cb:
            progress_cb(f"Writing section {i + 1}/{n}: {section.title}…")
        results.append(write_section(section, retriever, llm_client, user_prefs))
        if i < n - 1:                      # no delay after the last section
            time.sleep(request_delay)
    return results


def write_predicted_exam_paper(
    plan: ReviewPlan,
    retriever: BaseRetriever,
    llm_client: LLMClient,
    user_prefs: dict | None = None,
) -> str:
    """Generate Part B (predicted exam paper) for the exam_prediction task type."""
    user_prefs = user_prefs or {}

    # Build a ranked summary of all predicted sections
    sorted_sections = sorted(plan.sections, key=lambda s: s.importance, reverse=True)
    lines = []
    for i, sec in enumerate(sorted_sections, 1):
        topics_str = ", ".join(sec.key_topics)
        lines.append(
            f"{i}. **{sec.title}** (importance: {sec.importance}/5)\n"
            f"   Key topics: {topics_str}"
        )
    predicted_sections_text = "\n".join(lines)

    # Broad retrieval using top-importance section titles
    top_titles = " ".join(s.title for s in sorted_sections[:5])
    query = f"{plan.course_title} {top_titles}"
    docs: list[Document] = retriever.invoke(query)
    context = "\n\n".join(d.page_content for d in docs)

    prompt = ChatPromptTemplate.from_template(
        load_prompt("exam_prediction_paper_writer.md")
    )
    resp = llm_client.invoke(
        prompt.format_messages(
            course_name=user_prefs.get("course_name", ""),
            university_name=user_prefs.get("university_name", "") or "Not specified",
            major=user_prefs.get("major", "") or "Not specified",
            course_code=user_prefs.get("course_code", "") or "Not specified",
            professor_name=user_prefs.get("professor_name", "") or "Not specified",
            semester=user_prefs.get("semester", "") or "Not specified",
            exam_type=user_prefs.get("exam_type", "other"),
            exam_format=user_prefs.get("exam_format", "unknown"),
            exam_duration=user_prefs.get("exam_duration", "") or "Not specified",
            exam_info=user_prefs.get("exam_info", "") or "None provided",
            extra_instructions=user_prefs.get("extra_instructions", "") or "None",
            predicted_sections=predicted_sections_text,
            context=context,
        )
    )
    return getattr(resp, "content", str(resp))


def assemble_markdown(
    plan: ReviewPlan,
    sections: list[str],
    task_type: str = "review_summary",
    paper_text: str = "",
) -> str:
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

    # For exam_prediction: wrap analysis sections under Part A heading
    if tt == TaskType.exam_prediction and paper_text:
        md += "## Part A: Prediction Analysis\n\n"

    for s in sections:
        md += s + "\n\n"

    # Append the predicted exam paper as Part B
    if tt == TaskType.exam_prediction and paper_text:
        md += "\n---\n\n## Part B: Predicted Exam Paper\n\n"
        md += paper_text + "\n\n"

    return md


# ---------------------------------------------------------------------------
# Upload-cleanup helper
# ---------------------------------------------------------------------------

def wipe_session_uploads(session: "AgentSession") -> None:  # type: ignore[name-defined]
    """Delete all typed upload subfolders for *session*'s workspace.

    Called on every full re-index (Apply) so that workspace copies of files
    the user removed via the GUI are actually deleted from disk before the
    current file set is re-copied.  Also called directly when the user removes
    every file and clicks Apply — in that case the main pipeline is never
    entered, so the cleanup must happen at a higher level.

    Safe to call on a freshly-created session that has never been indexed.
    """
    if not session.workspace_id and not session.workspace_folder:
        return
    try:
        ws = workspace_paths(
            workspace_id=session.workspace_id,
            workspace_folder=session.workspace_folder,
        )
        for folder in ws.doc_folders.values():
            if folder.exists():
                shutil.rmtree(folder)
    except Exception:  # noqa: BLE001
        pass  # non-fatal; worst case the old copies linger until the next run


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
        workspace_folder: "Path | None" = None,
        progress_cb: Callable[[str], None] | None = None,
    ) -> tuple[ReviewPlan, str, str]:
        """Run the full RAG pipeline with classified documents.

        *workspace_folder*, if supplied, is used as the workspace root
        directly instead of the auto-computed path under the app data dir.

        Returns:
            Tuple of (ReviewPlan, markdown content, markdown file path)
        """
        def _progress(msg: str) -> None:
            if progress_cb:
                progress_cb(msg)

        ws = workspace_paths(workspace_id=workspace_id,
                             workspace_folder=workspace_folder)
        ensure_workspace_dirs(ws)

        _progress("Loading and splitting documents…")
        chunks = self.loader.load_and_split_classified(
            classified_files,
            workspace_paths=ws if copy_to_workspace else None,
        )

        if not chunks:
            raise LLMError("No document chunks were created. Please check your input files.")

        _progress(f"Building vector index ({len(chunks)} chunks)…")
        vectorstore = get_or_create_vectorstore(chunks, self.settings, ws,
                                                classified_files=classified_files)
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

        _progress("Generating study plan…")
        plan = generate_plan(all_docs, user_prefs, self.llm_client)

        if not plan.sections:
            raise LLMError("Generated an empty plan (no sections). Try again or adjust the prompt.")

        section_texts = write_sections_sequential(
            plan.sections,
            retriever,
            self.llm_client,
            user_prefs,
            request_delay=self.settings.llm_request_delay,
            progress_cb=progress_cb,
        )

        # For exam_prediction, generate the full predicted exam paper (Part B)
        paper_text = ""
        if task_type == TaskType.exam_prediction.value:
            _progress("Generating predicted exam paper…")
            paper_text = write_predicted_exam_paper(
                plan, retriever, self.llm_client, user_prefs
            )

        _progress("Assembling final document…")
        final_md = assemble_markdown(plan, section_texts, task_type, paper_text=paper_text)
        md_path = save_markdown(final_md, ws)
        return plan, final_md, md_path

    def prepare_session_fast(
        self,
        session: "AgentSession",  # type: ignore[name-defined]
    ) -> "BaseRetriever | None":  # type: ignore[name-defined]
        """Return a retriever by opening the existing ChromaDB — no re-indexing.

        Returns *None* when the database does not exist on disk or the current
        file set no longer matches what was indexed last time, signalling that a
        full :meth:`prepare_session` run is required.

        This path makes zero embedding API calls: the Chroma DB is opened
        directly from disk and the retriever is wrapped around it.
        """
        from uacragent.infra.vectorstore import chroma_is_current

        if not session.has_files():
            return None

        ws = workspace_paths(
            workspace_id=session.workspace_id,
            workspace_folder=session.workspace_folder,
        )

        if not chroma_is_current(ws, session.classified_files):
            return None

        # Open the existing store — empty chunk list means nothing is added or
        # removed.  Omitting classified_files prevents manifest rewrite.
        vectorstore = get_or_create_vectorstore([], self.settings, ws)
        return build_retriever(vectorstore, self.settings)

    def prepare_session(
        self,
        session: "AgentSession",  # type: ignore[name-defined]
        progress_cb: Callable[[str], None] | None = None,
    ) -> "BaseRetriever":  # type: ignore[name-defined]
        """Index session documents and return a ready-to-use retriever.

        Called by :class:`ConversationAgent` when the user initialises or
        reloads the session.  The retriever is stored on *session* by the
        caller.
        """
        def _progress(msg: str) -> None:
            if progress_cb:
                progress_cb(msg)

        ws = workspace_paths(
            workspace_id=session.workspace_id,
            workspace_folder=session.workspace_folder,
        )
        ensure_workspace_dirs(ws)

        # Wipe typed upload subfolders BEFORE re-copying so that workspace
        # copies of any files the user removed via the GUI are actually deleted.
        # load_and_split_classified will immediately re-copy only the files
        # that are still listed in session.classified_files.
        wipe_session_uploads(session)

        _progress("Loading and splitting documents…")
        chunks = self.loader.load_and_split_classified(
            session.classified_files,
            workspace_paths=ws,
        )

        if not chunks:
            raise ValueError(
                "No document chunks were created from the provided files. "
                "Please check that the files are readable."
            )

        _progress(f"Building vector index ({len(chunks)} chunks)…")
        vectorstore = get_or_create_vectorstore(chunks, self.settings, ws,
                                                classified_files=session.classified_files)
        return build_retriever(vectorstore, self.settings)

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
            copy_to_workspace=True,   # copy so manifest tracks files correctly
            university_name=university_name,
            major=major,
            course_code=course_code,
            professor_name=professor_name,
            semester=semester,
            exam_duration=exam_duration,
            exam_info=exam_info,
        )
