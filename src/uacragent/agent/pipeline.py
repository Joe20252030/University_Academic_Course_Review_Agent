from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.retrievers import BaseRetriever

from uacragent.agent.prompts._prompts import (
    PROMPTS_DIR as _PROMPTS_DIR,
    get_language_instruction as _get_language_instruction_impl,
)
from uacragent.export.markdown import save_markdown
from uacragent.domain.models import ReviewPlan, SectionSpec
from uacragent.domain.errors import IngestError, LLMError, ParseError
from uacragent.domain.types import DocumentType, TaskType
from uacragent.agent.reasoning import (
    get_reasoning_config,
    extract_topics,
    build_topic_context,
    apply_critic_pass,
)
from uacragent.infra.llm import LLMClient
from uacragent.infra.loaders import DocumentLoader
from uacragent.infra.settings import Settings
from uacragent.infra.vectorstore import (
    build_retriever, build_weighted_retriever,
    get_or_create_vectorstore, reset_manifest,
)
from uacragent.infra.workspace import ensure_workspace_dirs, workspace_paths, WorkspacePaths


# ---------------------------------------------------------------------------
# Effort level configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EffortConfig:
    """Retrieval and sampling parameters for a given effort level.

    Attributes
    ----------
    retriever_k      : chunks returned per RAG query (chat context + section writing)
    outline_max_docs : max documents sampled when building the plan outline
    outline_chars    : max characters taken from each sampled document in the outline
    """
    retriever_k:      int
    outline_max_docs: int
    outline_chars:    int


_EFFORT_CONFIGS: dict[str, EffortConfig] = {
    "low":    EffortConfig(retriever_k=4,  outline_max_docs=10, outline_chars=500),
    "medium": EffortConfig(retriever_k=8,  outline_max_docs=20, outline_chars=800),
    "high":   EffortConfig(retriever_k=16, outline_max_docs=40, outline_chars=1500),
}
_DEFAULT_EFFORT = "medium"


def get_effort_config(effort_level: str) -> EffortConfig:
    """Return the ``EffortConfig`` for *effort_level*, falling back to medium."""
    return _EFFORT_CONFIGS.get(effort_level, _EFFORT_CONFIGS[_DEFAULT_EFFORT])


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------
# _PROMPTS_DIR and _get_language_instruction_impl are imported at module top.

def _get_language_instruction(language: str) -> str:
    """Return the pipeline-variant language-steering instruction for *language*.

    Delegates to the central ``_prompts._get_language_instruction`` with
    ``pipeline=True`` so the shorter, generation-focused variant is used
    in planner and writer prompts.
    """
    return _get_language_instruction_impl(language, pipeline=True)

# Maps TaskType -> (planner prompt filename, writer prompt filename)
_PROMPT_FILES: dict[TaskType, tuple[str, str]] = {
    TaskType.review_summary: ("review_summary_planner.md", "review_summary_writer.md"),
    TaskType.practice_booklet: ("practice_booklet_planner.md", "practice_booklet_writer.md"),
    TaskType.mock_exam: ("mock_exam_planner.md", "mock_exam_writer.md"),
    TaskType.exam_prediction: ("exam_prediction_planner.md", "exam_prediction_writer.md"),
}

# Human-readable output title per task type — localised versions keyed by language code.
# The "en" entry is the authoritative fallback for any unknown language.
_TASK_TITLES_L10N: dict[str, dict[TaskType, str]] = {
    "en": {
        TaskType.review_summary:   "Exam Review",
        TaskType.practice_booklet: "Practice Booklet",
        TaskType.mock_exam:        "Mock Exam",
        TaskType.exam_prediction:  "Exam Prediction",
    },
    "zh_CN": {
        TaskType.review_summary:   "考试复习",
        TaskType.practice_booklet: "练习册",
        TaskType.mock_exam:        "模拟考试",
        TaskType.exam_prediction:  "考试预测",
    },
}


def _task_title(task_type: TaskType, language: str = "en") -> str:
    """Return the localised document title for *task_type*.

    Falls back to the English title if *language* is not registered, and to
    the string ``"Review"`` if the task type itself is not found.
    """
    titles = _TASK_TITLES_L10N.get(language) or _TASK_TITLES_L10N["en"]
    return titles.get(task_type) or _TASK_TITLES_L10N["en"].get(task_type, "Review")


# Language instructions are centralised in agent/prompts/_prompts.py.
# _get_language_instruction() is defined above next to the import.


def load_prompt(name: str) -> str:
    """Read a prompt template file by name from the prompts directory.

    Raises :class:`~uacragent.domain.errors.LLMError` with a clear message
    if the file is missing, rather than letting a bare ``FileNotFoundError``
    escape the ``UACRAgentError`` hierarchy.
    """
    prompt_path = _PROMPTS_DIR / name
    try:
        return prompt_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise LLMError(
            f"Prompt template '{name}' not found in {_PROMPTS_DIR}. "
            "This is an installation error — please reinstall the package."
        ) from None
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"Could not read prompt template '{name}': {exc}") from exc


def _get_prompt_files(task_type: TaskType) -> tuple[str, str]:
    """Return (planner_file, writer_file) for the given task type.

    Raises :class:`~uacragent.domain.errors.LLMError` if no prompt pair is
    registered for *task_type* — this would indicate an extension added a new
    ``TaskType`` value without wiring up the corresponding prompt files.
    """
    if task_type not in _PROMPT_FILES:
        raise LLMError(
            f"No prompt files registered for task type: {task_type!r}. "
            "Add an entry to _PROMPT_FILES in pipeline.py."
        )
    return _PROMPT_FILES[task_type]


# ---------------------------------------------------------------------------
# Pipeline functions
# ---------------------------------------------------------------------------

# Fields that must be present in every prompt template. Absent or empty values
# are replaced with human-readable fallbacks before the prompt is rendered.
_PROMPT_FIELD_DEFAULTS: dict[str, str] = {
    "university_name": "Not specified",
    "major":           "Not specified",
    "course_code":     "Not specified",
    "professor_name":  "Not specified",
    "semester":        "Not specified",
    "exam_duration":   "Not specified",
    "exam_info":       "None provided",
    "extra_instructions": "None",
}


def _expand_user_prefs(user_prefs: dict) -> dict:
    """Return a copy of *user_prefs* with empty optional fields replaced by
    human-readable fallbacks used in every prompt template.

    Centralises the ``or "Not specified"`` pattern that previously appeared
    three times across ``generate_plan``, ``write_section``, and
    ``write_predicted_exam_paper``.
    """
    out = dict(user_prefs)
    for key, default in _PROMPT_FIELD_DEFAULTS.items():
        if not out.get(key):
            out[key] = default
    return out


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
        # Linspace-style sampling: includes both the first and last document so
        # the planner sees material from the full range of the corpus.
        # The previous step-based approach missed the last document when
        # len(docs) is not a multiple of max_docs.
        sampled = [
            docs[round(i * (len(docs) - 1) / (max_docs - 1))]
            for i in range(max_docs)
        ]

    parts = [d.page_content[:chars_per_doc] for d in sampled]
    return "\n\n".join(parts).strip()


def generate_plan(
    docs: list[Document],
    user_prefs: dict,
    llm_client: LLMClient,
    max_docs: int = 20,
    chars_per_doc: int = 800,
    _outline_override: str | None = None,
    language: str = "en",
    cancel_event: "threading.Event | None" = None,
) -> ReviewPlan:
    """Generate a :class:`ReviewPlan` from document chunks.

    *_outline_override* allows the caller to supply a pre-built (and
    optionally augmented) outline string instead of building it from scratch.
    Used by the Deep Analysis path to inject topic-priority context into the
    planner prompt without rebuilding the outline a second time.

    *language* steers the output language of the generated plan (``"en"`` or
    ``"zh_CN"``).
    """
    outline_text = (
        _outline_override
        if _outline_override is not None
        else build_outline(docs, max_docs=max_docs, chars_per_doc=chars_per_doc)
    )

    task_type = TaskType(user_prefs.get("task_type", "review_summary"))
    planner_file, _ = _get_prompt_files(task_type)
    prompt = ChatPromptTemplate.from_template(load_prompt(planner_file))

    p = _expand_user_prefs(user_prefs)
    messages = prompt.format_messages(
        outline=outline_text,
        exam_format=p.get("exam_format", "unknown"),
        exam_type=p.get("exam_type", "other"),
        extra_instructions=p["extra_instructions"],
        course_name=p.get("course_name", ""),
        university_name=p["university_name"],
        major=p["major"],
        course_code=p["course_code"],
        professor_name=p["professor_name"],
        semester=p["semester"],
        exam_duration=p["exam_duration"],
        exam_info=p["exam_info"],
        response_language=_get_language_instruction(language),
    )

    plan: ReviewPlan = llm_client.generate_structured_cancellable(
        ReviewPlan, messages, cancel_event
    )
    if plan is None:
        if cancel_event and cancel_event.is_set():
            raise LLMError("Generation was cancelled.")
        raise ParseError(
            "The LLM returned an empty response when asked to generate a study plan. "
            "Try again or adjust your course settings."
        )
    return plan


def write_section(
    section: SectionSpec,
    retriever: BaseRetriever,
    llm_client: LLMClient,
    user_prefs: dict | None = None,
    language: str = "en",
    cancel_event: "threading.Event | None" = None,
) -> str:
    """Write the prose body for a single outline section.

    Retrieves relevant documents from *retriever* using the section title and
    key topics as the query, then calls *llm_client* with the appropriate task
    writer prompt to produce the section's Markdown text.

    Args:
        section:     The :class:`SectionSpec` describing this outline entry.
        retriever:   A LangChain retriever backed by the session's vectorstore.
        llm_client:  The configured LLM wrapper for this session.
        user_prefs:  Optional dict from :meth:`Session.to_user_prefs` carrying
                     course metadata, task type, and effort level.
        language:    BCP-47 locale tag forwarded to the writer prompt.

    Returns:
        The section body as a Markdown string.
    """
    user_prefs = user_prefs or {}

    query = section.title + " " + " ".join(section.key_topics)
    docs: list[Document] = retriever.invoke(query)
    context = "\n\n".join(d.page_content for d in docs)

    key_topics_text = "\n".join(f"- {t}" for t in section.key_topics)

    task_type = TaskType(user_prefs.get("task_type", "review_summary"))
    _, writer_file = _get_prompt_files(task_type)
    prompt = ChatPromptTemplate.from_template(load_prompt(writer_file))

    p = _expand_user_prefs(user_prefs)
    resp = llm_client.stream_invoke(
        prompt.format_messages(
            title=section.title,
            key_topics=key_topics_text,
            context=context,
            exam_type=p.get("exam_type", "other"),
            exam_format=p.get("exam_format", "unknown"),
            extra_instructions=p["extra_instructions"],
            course_name=p.get("course_name", ""),
            university_name=p["university_name"],
            major=p["major"],
            course_code=p["course_code"],
            professor_name=p["professor_name"],
            semester=p["semester"],
            exam_duration=p["exam_duration"],
            exam_info=p["exam_info"],
            response_language=_get_language_instruction(language),
        ),
        cancel_event=cancel_event,
    )
    if resp is None:
        return ""  # Cancelled mid-generation
    return getattr(resp, "content", str(resp))


def write_sections_sequential(
    sections: list[SectionSpec],
    retriever: BaseRetriever,
    llm_client: LLMClient,
    user_prefs: dict | None = None,
    request_delay: float = 6.0,
    progress_cb: Callable[[str], None] | None = None,
    enable_critic: bool = False,
    cancel_event: "threading.Event | None" = None,
    language: str = "en",
) -> list[str]:
    """Write sections one at a time with a delay between each LLM call.

    Sequential execution guarantees that only one request is in-flight at any
    moment. The delay is inserted *after* each completed call (not before the
    next submission), so it is always respected regardless of how long the
    previous call took. In normal app usage this value comes from
    ``Settings.llm_request_delay``, which is usually controlled through the
    selected ``RATE_TIER``.

    When *enable_critic* is ``True`` (Deep Analysis mode), each section is
    passed through a refinement LLM call after the initial write.  A separate
    inter-call delay is inserted after the critic call as well to respect rate
    limits.  The critic pass counts as an additional LLM call per section.
    """
    def _interruptible_sleep(duration: float) -> bool:
        """Sleep for *duration* seconds, waking every 0.1 s to check cancel.

        Returns True if cancelled, False if the full sleep completed.
        """
        slept = 0.0
        while slept < duration:
            if cancel_event and cancel_event.is_set():
                return True
            time.sleep(min(0.1, duration - slept))
            slept += 0.1
        return False

    results: list[str] = []
    n = len(sections)
    for i, section in enumerate(sections):
        if cancel_event and cancel_event.is_set():
            # Return whatever has been completed so far instead of discarding
            # all work — a cancellation at 90% completion should still yield
            # the already-written sections rather than an empty document.
            return results
        if progress_cb:
            progress_cb(f"Writing section {i + 1}/{n}: {section.title}…")
        text = write_section(
            section, retriever, llm_client, user_prefs,
            language=language, cancel_event=cancel_event,
        )
        if cancel_event and cancel_event.is_set():
            return results  # Section was cancelled mid-generation; discard empty result

        # Deep Analysis: run a refinement / critic pass on each section.
        if enable_critic:
            if progress_cb:
                progress_cb(
                    f"Reviewing section {i + 1}/{n}: {section.title}…"
                )
            # Interruptible sleep before the critic call so cancel is responsive.
            if _interruptible_sleep(request_delay):
                return results  # return partial results, not empty list
            text = apply_critic_pass(
                section_text=text,
                section_title=section.title,
                key_topics=list(section.key_topics),
                llm_client=llm_client,
                cancel_event=cancel_event,
            )
            if cancel_event and cancel_event.is_set():
                results.append(text)  # text is the pre-critic original; include it
                return results

        results.append(text)

        if i < n - 1:                      # no delay after the last section
            # Interruptible sleep: check cancel every 0.1 s so cancellation is
            # responsive even during long rate-limit delays.
            if _interruptible_sleep(request_delay):
                return results  # return partial results, not empty list
    return results


def write_predicted_exam_paper(
    plan: ReviewPlan,
    retriever: BaseRetriever,
    llm_client: LLMClient,
    user_prefs: dict | None = None,
    language: str = "en",
    cancel_event: "threading.Event | None" = None,
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
    p = _expand_user_prefs(user_prefs)
    resp = llm_client.stream_invoke(
        prompt.format_messages(
            course_name=p.get("course_name", ""),
            university_name=p["university_name"],
            major=p["major"],
            course_code=p["course_code"],
            professor_name=p["professor_name"],
            semester=p["semester"],
            exam_type=p.get("exam_type", "other"),
            exam_format=p.get("exam_format", "unknown"),
            exam_duration=p["exam_duration"],
            exam_info=p["exam_info"],
            extra_instructions=p["extra_instructions"],
            predicted_sections=predicted_sections_text,
            context=context,
            response_language=_get_language_instruction(language),
        ),
        cancel_event=cancel_event,
    )
    if resp is None:
        return ""  # Cancelled mid-generation
    return getattr(resp, "content", str(resp))


def assemble_markdown(
    plan: ReviewPlan,
    sections: list[str],
    task_type: str = "review_summary",
    paper_text: str = "",
    language: str = "en",
) -> str:
    """Combine a :class:`ReviewPlan` and its written section bodies into a
    single cohesive Markdown document.

    Builds a rich header (course title, university, major, date) and joins each
    section body under its title heading.  When *paper_text* is provided it is
    appended as an appendix.

    Args:
        plan:        The review plan produced by :func:`generate_plan`.
        sections:    List of prose bodies in the same order as *plan.sections*.
        task_type:   Task-type string (e.g. ``"review_summary"`` or
                     ``"mock_exam"``).  Controls the document title suffix.
        paper_text:  Optional plain-text content of an uploaded exam paper to
                     append as an appendix.
        language:    BCP-47 locale tag used for the title suffix lookup.

    Returns:
        The assembled document as a single Markdown string.
    """
    try:
        tt = TaskType(task_type)
    except ValueError:
        tt = TaskType.review_summary
    title_suffix = _task_title(tt, language)

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
# Upload-cleanup helpers (re-exported from workspace_manager for compatibility)
# ---------------------------------------------------------------------------
# These functions have moved to agent/workspace_manager.py.
# The re-export here preserves backward compatibility for any callers that
# import them from pipeline (e.g. existing tests or external scripts).

from uacragent.agent.workspace_manager import (  # noqa: E402
    wipe_session_uploads,
    wipe_session_vectorstore,
)


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
        effort_level: str = "medium",
        reasoning_mode: str = "quick",
        language: str = "en",
        cancel_event: "threading.Event | None" = None,
    ) -> tuple[ReviewPlan, str, str]:
        """Run the full RAG pipeline with classified documents.

        *workspace_folder*, if supplied, is used as the workspace root
        directly instead of the auto-computed path under the app data dir.

        *reasoning_mode* selects the depth of the generation pipeline:

        - ``"quick"``  — single-pass, lower token usage, faster response.
        - ``"deep"``   — topic extraction + critic refinement, higher quality.

        Returns:
            Tuple of (ReviewPlan, markdown content, markdown file path)
        """
        def _progress(msg: str) -> None:
            if progress_cb:
                progress_cb(msg)

        def _check_cancelled() -> None:
            if cancel_event and cancel_event.is_set():
                raise LLMError("Generation was cancelled.")

        ws = workspace_paths(workspace_id=workspace_id,
                             workspace_folder=workspace_folder)
        ensure_workspace_dirs(ws)

        _check_cancelled()
        _progress("Loading and splitting documents…")
        chunks = self.loader.load_and_split_classified(
            classified_files,
            workspace_paths=ws if copy_to_workspace else None,
        )

        if not chunks:
            raise IngestError(
                "No document chunks were created from the provided files. "
                "Please check that the files are readable and not empty."
            )

        _check_cancelled()
        _progress(f"Building vector index ({len(chunks)} chunks)…")
        vectorstore, _ = get_or_create_vectorstore(chunks, self.settings, ws,
                                                   classified_files=classified_files)

        # ── Apply reasoning mode scales on top of effort config ──────────────
        # Both axes (effort level and reasoning mode) are independent sliders:
        # effort controls absolute retrieval size; reasoning mode scales it
        # further to reflect quick vs. deep pipeline requirements.
        effort = get_effort_config(effort_level)
        reasoning_cfg = get_reasoning_config(reasoning_mode)

        scaled_k = max(1, int(effort.retriever_k * reasoning_cfg.retriever_k_scale))
        scaled_chars = max(200, int(effort.outline_chars * reasoning_cfg.outline_chars_scale))
        scaled_max_docs = max(5, int(
            effort.outline_max_docs * reasoning_cfg.outline_max_docs_scale
        ))

        # Convert task_type string to enum once at the top, and use tt everywhere.
        tt = TaskType(task_type)

        # Build a task-type-aware retriever whose k is scaled to effort level
        # and reasoning mode.  WeightedDocTypeRetriever allocates more k slots
        # to higher-priority doc types (e.g. past_exam for exam_prediction).
        retriever = build_weighted_retriever(
            vectorstore,
            k=scaled_k,
            task_type=tt,
            classified_files=classified_files,
        )

        # Re-use the already-loaded chunks for plan generation instead of
        # reloading every file from disk a second time.  build_outline()
        # only samples page_content, so split chunks work equally well.
        user_prefs = {
            "exam_format": exam_format,
            "exam_type": exam_type,
            "task_type": tt.value,
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

        # ── Deep Analysis: structured topic extraction ────────────────────────
        # Before building the plan outline, extract a ranked list of
        # exam-relevant topics from the documents.  The topic priority block
        # is appended to the outline text so the planner can weight its
        # section selection toward high-importance topics.
        outline_text = build_outline(chunks, max_docs=scaled_max_docs,
                                     chars_per_doc=scaled_chars)
        if reasoning_cfg.enable_topic_extraction:
            _progress("Deep Analysis: extracting topic priorities…")
            topic_list = extract_topics(
                outline_text, user_prefs, self.llm_client, cancel_event=cancel_event
            )
            _check_cancelled()
            topic_block = build_topic_context(topic_list)
            if topic_block:
                outline_text = outline_text + topic_block
                _progress(
                    f"Deep Analysis: {len(topic_list.topics)} topics identified."
                    if topic_list else "Deep Analysis: topic extraction skipped."
                )

        _check_cancelled()
        _progress("Generating study plan…")
        plan = generate_plan(
            chunks, user_prefs, self.llm_client,
            max_docs=scaled_max_docs,
            chars_per_doc=scaled_chars,
            _outline_override=outline_text,
            language=language,
            cancel_event=cancel_event,
        )

        if not plan.sections:
            raise LLMError("Generated an empty plan (no sections). Try again or adjust the prompt.")

        # ── Apply section cap (Quick mode limits to N sections) ───────────────
        if reasoning_cfg.max_sections and len(plan.sections) > reasoning_cfg.max_sections:
            # Preserve the most important sections ranked by planner importance.
            top_sections = sorted(
                plan.sections, key=lambda s: s.importance, reverse=True
            )[: reasoning_cfg.max_sections]
            plan = plan.model_copy(update={"sections": top_sections})

        section_texts = write_sections_sequential(
            plan.sections,
            retriever,
            self.llm_client,
            user_prefs,
            request_delay=self.settings.llm_request_delay,
            progress_cb=progress_cb,
            enable_critic=reasoning_cfg.enable_critic_pass,
            cancel_event=cancel_event,
            language=language,
        )
        _check_cancelled()

        # For exam_prediction, generate the full predicted exam paper (Part B)
        paper_text = ""
        if tt == TaskType.exam_prediction:
            _check_cancelled()
            _progress("Generating predicted exam paper…")
            paper_text = write_predicted_exam_paper(
                plan, retriever, self.llm_client, user_prefs,
                language=language, cancel_event=cancel_event,
            )
            _check_cancelled()

        _progress("Assembling final document…")
        final_md = assemble_markdown(plan, section_texts, tt.value, paper_text=paper_text,
                                     language=language)
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

        if not chroma_is_current(ws, session.classified_files, self.settings):
            return None

        # Open the existing store — empty chunk list means nothing is added or
        # removed.  Omitting classified_files prevents manifest rewrite so no
        # manifest warning can occur on the fast path.
        vectorstore, _ = get_or_create_vectorstore([], self.settings, ws)
        return build_retriever(vectorstore, self.settings)

    def prepare_session(
        self,
        session: "AgentSession",  # type: ignore[name-defined]
        progress_cb: Callable[[str], None] | None = None,
    ) -> "tuple[BaseRetriever, str | None]":  # type: ignore[name-defined]
        """Index session documents and return a ready-to-use retriever.

        Returns
        -------
        (retriever, manifest_warning)
            *manifest_warning* is ``None`` on full success, or a human-readable
            string when the indexing manifest could not be saved — meaning the
            next session open will re-index from scratch instead of using the
            fast path.  The caller should surface this to the user.
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
            raise IngestError(
                "No document chunks were created from the provided files. "
                "Please check that the files are readable."
            )

        _progress(f"Building vector index ({len(chunks)} chunks)…")
        vectorstore, manifest_warning = get_or_create_vectorstore(
            chunks, self.settings, ws,
            classified_files=session.classified_files,
            progress_cb=_progress,
        )
        return build_retriever(vectorstore, self.settings), manifest_warning
