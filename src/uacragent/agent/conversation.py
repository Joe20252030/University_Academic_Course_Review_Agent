"""ConversationAgent — drives the chat loop and delegates task generation."""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from uacragent.agent.session import AgentSession
from uacragent.domain.errors import LLMError
from uacragent.domain.types import TaskType
from uacragent.infra.llm import LLMClient
from uacragent.infra.settings import Settings, get_settings

# ---------------------------------------------------------------------------
# MIME type map for file attachments
# ---------------------------------------------------------------------------

_MIME_MAP: dict[str, str] = {
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif":  "image/gif",
    ".webp": "image/webp",
    ".bmp":  "image/bmp",
    ".pdf":  "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt":  "text/plain",
    ".md":   "text/markdown",
    ".py":   "text/x-python",
    ".js":   "text/javascript",
    ".ts":   "text/typescript",
    ".csv":  "text/csv",
    ".json": "application/json",
    ".xml":  "text/xml",
    ".html": "text/html",
    ".htm":  "text/html",
}

_IMAGE_MIMES = {
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp",
}
_TEXT_MIMES = {
    "text/plain", "text/markdown", "text/x-python", "text/javascript",
    "text/typescript", "text/csv", "application/json", "text/xml",
    "text/html",
}


def _extract_file_text(path: str, mime: str) -> str:
    """Extract text from a file given its path and MIME type.

    Uses PyPDFLoader for PDFs, Docx2txtLoader for Word documents, and
    plain utf-8 text reading for all other supported text-based formats.
    Returns extracted text, or an error notice string on failure.
    """
    try:
        if mime == "application/pdf":
            from langchain_community.document_loaders import PyPDFLoader
            docs = PyPDFLoader(path).load()
            return "\n\n".join(d.page_content for d in docs)
        elif mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            from langchain_community.document_loaders import Docx2txtLoader
            docs = Docx2txtLoader(path).load()
            return "\n\n".join(d.page_content for d in docs)
        else:
            return Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return f"[Could not extract text from {Path(path).name}: {exc}]"


def _build_human_message(
    message_text: str,
    attachments: list[dict],
    provider_id: str,
) -> "HumanMessage":
    """Build a HumanMessage with optional multimodal content parts.

    For image attachments: base64-encoded inline ``image_url`` content parts.
    For PDFs / Word docs / text files: extracted text appended to the message.
    When there are no attachments, returns a plain HumanMessage(content=...).
    """
    if not attachments:
        return HumanMessage(content=message_text)

    import base64

    parts: list = []
    extra_text_blocks: list[str] = []

    for att in attachments:
        path = att.get("path", "")
        mime = att.get("mime", "application/octet-stream")
        name = att.get("name", Path(path).name)

        if mime in _IMAGE_MIMES:
            # Inline base64 image — supported by Gemini and OpenAI
            try:
                data = Path(path).read_bytes()
                b64  = base64.b64encode(data).decode()
                parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                })
            except Exception as exc:  # noqa: BLE001
                extra_text_blocks.append(
                    f"[Could not encode image {name}: {exc}]"
                )
        else:
            # Text-based or document file — extract and append as text
            extracted = _extract_file_text(path, mime)
            extra_text_blocks.append(
                f"\n\n--- Attached file: {name} ---\n{extracted}\n---"
            )

    # Compose message text with any extracted text blocks
    full_text = message_text
    if extra_text_blocks:
        full_text = message_text + "".join(extra_text_blocks)

    if parts:
        # Multimodal content list: text part first, then image parts
        content: list = [{"type": "text", "text": full_text}] + parts
        return HumanMessage(content=content)
    else:
        return HumanMessage(content=full_text)


def _settings_for_session(base: Settings, session: AgentSession) -> Settings:
    """Return a Settings instance with provider/model overridden from the session.

    Uses ``model_copy`` instead of mutating ``os.environ`` so that concurrent
    background threads cannot race on the global environment.
    """
    updates: dict = {}
    if session.llm_provider:
        updates["llm_provider"] = session.llm_provider
    if session.llm_model:
        updates["llm_model"] = session.llm_model
    if updates:
        return base.model_copy(update=updates)
    return base

_PROMPTS_DIR = Path(__file__).parent / "prompts"

# ---------------------------------------------------------------------------
# Localised strings used inside agent responses
# ---------------------------------------------------------------------------

# Strings returned by initialize_session() as the session-status message.
_INIT_STATUS: dict[str, dict[str, str]] = {
    "en": {
        "no_docs": (
            "No documents are loaded yet. "
            "Add files in the Session Settings panel and click **Apply** to index them."
        ),
        "ready_cached": (
            "Session ready. {n_files} file(s) across {n_types} "
            "document type(s) already indexed."
        ),
        "ready_indexed": (
            "Session ready. Indexed {n_files} file(s) across {n_types} document "
            "type(s). You can now ask questions or request a study document."
        ),
        "init_failed": "Failed to initialise session: {exc}",
    },
    "zh_CN": {
        "no_docs": (
            "尚未加载任何文档。"
            "请在会话设置面板添加文件，然后点击**应用**进行索引。"
        ),
        "ready_cached": (
            "会话就绪。已有 {n_files} 个文件（{n_types} 种文档类型）完成索引。"
        ),
        "ready_indexed": (
            "会话就绪。已成功索引 {n_files} 个文件（{n_types} 种文档类型）。"
            "您可以提问或请求生成学习文档。"
        ),
        "init_failed": "会话初始化失败：{exc}",
    },
}

# Strings embedded in chat replies (generation errors, document-save notes).
_CHAT_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "no_docs_err": (
            "No documents are loaded. Please add files in the Session Settings "
            "panel and index them before generating a document."
        ),
        "not_init_err": (
            "The session has not been initialised yet. "
            "Click **Apply** to index your documents first."
        ),
        "gen_failed": "Generation failed: {exc}",
        "doc_saved": (
            "\n\n📄 The document has been saved as **{name}** "
            "in the outputs folder of your workspace.\n"
            "Full path: `{path}`\n\n"
            "*(This file remains on disk permanently — use the path above "
            "to locate it if you close and reopen the app.)*"
        ),
    },
    "zh_CN": {
        "no_docs_err": (
            "未加载任何文档。请在会话设置面板添加文件并完成索引后，再生成文档。"
        ),
        "not_init_err": (
            "会话尚未初始化，请先点击**应用**对文档进行索引。"
        ),
        "gen_failed": "生成失败：{exc}",
        "doc_saved": (
            "\n\n📄 文档已保存为 **{name}**，"
            "位于工作空间的 outputs 文件夹中。\n"
            "完整路径：`{path}`\n\n"
            "*(此文件将永久保存在磁盘上——关闭并重新打开应用后可通过上述路径找到。)*"
        ),
    },
}

# Language instructions injected into the system prompt.
_LANGUAGE_INSTRUCTIONS: dict[str, str] = {
    "en": "",   # English is the default; no explicit instruction needed.
    "zh_CN": (
        "## Language Requirement\n\n"
        "You MUST respond entirely in Simplified Chinese (简体中文). "
        "All replies, explanations, section headings, and any generated "
        "document content must be written in Chinese. "
        "Do not mix in English unless quoting technical terms that have no "
        "standard Chinese translation."
    ),
}


def _ls(lang: str, table: dict[str, dict[str, str]], key: str, **fmt: object) -> str:
    """Look up *key* in *table* for *lang*, falling back to English.

    Any *fmt* keyword arguments are passed to ``str.format`` so callers can
    inline placeholders without a separate format call.
    """
    row = table.get(lang) or table["en"]
    text = row.get(key) or table["en"].get(key, key)
    return text.format(**fmt) if fmt else text


# Regex that matches a [TASK:xxx] marker on its own line (optional trailing whitespace)
_TASK_MARKER_RE = re.compile(
    r"\[TASK:(review_summary|practice_booklet|mock_exam|exam_prediction)\]",
    re.IGNORECASE,
)


def _extract_task_marker(text: str) -> tuple[str | None, str]:
    """Return ``(task_type_value, cleaned_text)`` after stripping the marker.

    The LLM embeds a ``[TASK:xxx]`` token to signal that a generation pipeline
    should be triggered.  This function detects the token, extracts the task
    type, and removes the token from the text shown to the user.
    """
    match = _TASK_MARKER_RE.search(text)
    if match is None:
        return None, text.strip()
    task_value = match.group(1).lower()
    clean = _TASK_MARKER_RE.sub("", text).strip()
    return task_value, clean


@dataclass
class ChatResponse:
    """Result returned by ConversationAgent.chat()."""

    text: str                       # assistant message shown to the user
    output_path: str | None = None  # set when a task document was generated
    task_type: str | None = None    # the TaskType value that was triggered, if any
    error: str | None = None        # set when generation failed


class ConversationAgent:
    """Stateless agent that holds only shared infrastructure.

    All per-session state lives in :class:`AgentSession`.  Pass the same
    session object across multiple ``chat()`` calls to maintain continuity.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings: Settings = settings or get_settings()

    # ------------------------------------------------------------------
    # Session initialisation
    # ------------------------------------------------------------------

    def initialize_session(
        self,
        session: AgentSession,
        progress_cb: Callable[[str], None] | None = None,
        force_reindex: bool = False,
        language: str = "en",
    ) -> tuple[str, bool]:
        """Build or reuse the retriever for *session*.

        Returns ``(status_message, was_cached)`` where *was_cached* is ``True``
        when the existing ChromaDB was opened directly without any re-embedding.

        When *force_reindex* is ``True`` the fast path is skipped and a full
        indexing run is always performed (used by the Apply button so that
        changes to embedding provider, model, or files always take effect).

        *language* controls which locale is used for the returned status message
        (``"en"`` or ``"zh_CN"``).
        """
        from uacragent.agent.pipeline import AgentPipeline

        if not session.has_files():
            session.retriever = None
            # When the user removed every file and clicked Apply, the pipeline
            # is never entered — wipe uploads, chroma_db, and the manifest here.
            if force_reindex:
                from uacragent.agent.pipeline import (
                    wipe_session_uploads, wipe_session_vectorstore)
                wipe_session_uploads(session)
                wipe_session_vectorstore(session)
            return (_ls(language, _INIT_STATUS, "no_docs"), False)

        try:
            settings = _settings_for_session(self.settings, session)
            pipeline = AgentPipeline(settings)

            # ── Fast path: reuse existing ChromaDB without re-embedding ────────
            if not force_reindex:
                try:
                    retriever = pipeline.prepare_session_fast(session)
                    if retriever is not None:
                        session.retriever = retriever
                        n_files = sum(len(v) for v in session.active_files().values())
                        n_types = len(session.active_files())
                        return (
                            _ls(language, _INIT_STATUS, "ready_cached",
                                n_files=n_files, n_types=n_types),
                            True,
                        )
                except Exception:  # noqa: BLE001
                    pass  # fall through to full indexing

            # ── Full indexing path ──────────────────────────────────────────────
            session.retriever = pipeline.prepare_session(session, progress_cb=progress_cb)
            n_types = len(session.active_files())
            n_files = sum(len(v) for v in session.active_files().values())
            return (
                _ls(language, _INIT_STATUS, "ready_indexed",
                    n_files=n_files, n_types=n_types),
                False,
            )
        except Exception as exc:  # noqa: BLE001
            session.retriever = None
            return (_ls(language, _INIT_STATUS, "init_failed", exc=exc), False)

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    def chat(
        self,
        message: str,
        session: AgentSession,
        progress_cb: Callable[[str], None] | None = None,
        effort_level: str = "medium",
        language: str = "en",
        search_enabled: bool = False,
        attachments: list | None = None,
    ) -> ChatResponse:
        """Process one user turn and return a :class:`ChatResponse`.

        *effort_level* controls how much retrieved context is injected into the
        system prompt and how deeply the generation pipeline samples the corpus.
        Valid values: ``"low"``, ``"medium"`` (default), ``"high"``.

        *language* steers the LLM's response language via the system prompt
        and is used to localise any agent-generated error or status text
        embedded in the reply (``"en"`` or ``"zh_CN"``).

        Flow:
        1. Retrieve relevant context (if retriever is available).
        2. Build a message list: system prompt + history + new human message.
        3. Call the LLM.
        4. Strip any ``[TASK:xxx]`` marker from the response text.
        5. If a task marker was found, run the generation pipeline.
        6. Append the turn to *session.chat_history* and trim if needed.
        7. Return a ChatResponse.
        """
        # -- 1. Retrieve context -----------------------------------------------
        context = self._retrieve_context(message, session, effort_level)

        # -- 2. Build message list ---------------------------------------------
        provider_id = (session.llm_provider or "gemini").lower()
        system_content = self._render_system_prompt(session, context, language=language)
        messages: list = [SystemMessage(content=system_content)]
        # Use snapshot() to get a consistent, lock-safe copy of history.
        # This prevents a concurrent cancel from mutating the list mid-iteration.
        messages.extend(session.chat_history.snapshot())
        messages.append(
            _build_human_message(message, attachments or [], provider_id)
        )

        # -- 3. Call LLM (use session provider/model if different from default) --
        llm = LLMClient(_settings_for_session(self.settings, session))
        try:
            if search_enabled:
                raw_response = llm.invoke_with_search(messages, provider_id)
            else:
                raw_response = llm.invoke(messages)
            content = getattr(raw_response, "content", str(raw_response))
            if isinstance(content, list):
                assistant_text: str = " ".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content
                    if isinstance(part, str) or (isinstance(part, dict) and part.get("type") == "text")
                ).strip() or str(content)
            else:
                assistant_text = str(content)
        except Exception as exc:  # noqa: BLE001
            error_msg = f"LLM call failed: {exc}"
            return ChatResponse(text=error_msg, error=error_msg)

        # -- 4. Detect and strip task marker -----------------------------------
        task_type, clean_text = _extract_task_marker(assistant_text)

        # -- 5. Run generation pipeline if task was requested ------------------
        output_path: str | None = None
        generation_error: str | None = None

        if task_type is not None:
            if not session.has_files():
                generation_error = _ls(language, _CHAT_STRINGS, "no_docs_err")
            elif session.retriever is None:
                generation_error = _ls(language, _CHAT_STRINGS, "not_init_err")
            else:
                try:
                    output_path = self._run_task(
                        task_type, session, progress_cb, effort_level, language
                    )
                except Exception as exc:  # noqa: BLE001
                    generation_error = _ls(language, _CHAT_STRINGS, "gen_failed", exc=exc)

        # -- 6. Build final reply text -----------------------------------------
        reply = clean_text
        if output_path:
            p = Path(output_path)
            reply += _ls(language, _CHAT_STRINGS, "doc_saved",
                         name=p.name, path=output_path)
        if generation_error:
            reply += f"\n\n⚠️ {generation_error}"

        # -- 7. Update history (after reply is fully assembled) ----------------
        # Save `reply` — not `clean_text` — so the file path note and any error
        # message are preserved across session reloads.
        # append_turn() inserts both messages atomically so a concurrent cancel
        # can never observe one message without the other.
        session.chat_history.append_turn(
            HumanMessage(content=message),
            AIMessage(content=reply),
        )
        session.trim_history()

        return ChatResponse(
            text=reply,
            output_path=output_path,
            task_type=task_type,
            error=generation_error,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _retrieve_context(
        self, message: str, session: AgentSession, effort_level: str = "medium"
    ) -> str:
        """Return retrieved context text scaled to *effort_level*.

        Uses the vectorstore directly with an effort-calibrated *k* so that
        Low/Medium/High effort controls how many chunks are injected into the
        system prompt without rebuilding the retriever.
        """
        if session.retriever is None:
            return "*(No documents loaded — answers are based on general knowledge only.)*"
        try:
            from uacragent.agent.pipeline import get_effort_config
            effort = get_effort_config(effort_level)

            # Prefer direct vectorstore access so we can override k at call time.
            # VectorStoreRetriever exposes `.vectorstore`; fall back to the
            # retriever itself (with its fixed k) when that attribute is absent.
            try:
                docs = session.retriever.vectorstore.similarity_search(
                    message, k=effort.retriever_k
                )
            except AttributeError:
                docs = session.retriever.invoke(message)

            if not docs:
                return "*(No relevant excerpts found in the uploaded documents.)*"
            return "\n\n".join(d.page_content for d in docs)
        except Exception:  # noqa: BLE001
            return "*(Context retrieval failed — answers are based on general knowledge only.)*"

    def _render_system_prompt(
        self, session: AgentSession, context: str, language: str = "en"
    ) -> str:
        """Fill the system prompt template with session values.

        *language* is used to inject a language-steering instruction so the LLM
        responds in the user's chosen locale (``"en"`` or ``"zh_CN"``).
        """
        prompt_path = _PROMPTS_DIR / "conversation_system.md"
        try:
            template = prompt_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise LLMError(
                f"System prompt template not found at {prompt_path}. "
                "This is an installation error — please reinstall the package."
            ) from None
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Could not read system prompt template: {exc}") from exc

        prefs = session.to_user_prefs()

        # Build a compact course meta suffix for the opening line
        meta_parts = []
        if prefs.get("course_code"):
            meta_parts.append(prefs["course_code"])
        if prefs.get("semester"):
            meta_parts.append(prefs["semester"])
        course_meta = f" ({', '.join(meta_parts)})" if meta_parts else ""

        has_files_text = (
            ", ".join(
                f"{len(v)} {k.replace('_', ' ')}"
                for k, v in session.active_files().items()
            )
            if session.has_files()
            else "None"
        )

        response_language = _LANGUAGE_INSTRUCTIONS.get(language, "")

        return template.format(
            course_name=prefs.get("course_name") or "this course",
            course_meta=course_meta,
            university_name=prefs.get("university_name") or "Not specified",
            major=prefs.get("major") or "Not specified",
            course_code=prefs.get("course_code") or "Not specified",
            professor_name=prefs.get("professor_name") or "Not specified",
            semester=prefs.get("semester") or "Not specified",
            exam_type=prefs.get("exam_type") or "other",
            exam_format=prefs.get("exam_format") or "written",
            exam_duration=prefs.get("exam_duration") or "Not specified",
            exam_info=prefs.get("exam_info") or "None provided",
            extra_instructions=prefs.get("extra_instructions") or "None",
            has_files=has_files_text,
            context=context,
            response_language=response_language,
        )

    def _run_task(
        self,
        task_type: str,
        session: AgentSession,
        progress_cb: Callable[[str], None] | None = None,
        effort_level: str = "medium",
        language: str = "en",
    ) -> str:
        """Run the generation pipeline and return the output markdown path."""
        from uacragent.agent.pipeline import AgentPipeline

        pipeline = AgentPipeline(_settings_for_session(self.settings, session))
        prefs = session.to_user_prefs()

        _, _, md_path = pipeline.run_end_to_end(
            classified_files=session.classified_files,
            exam_format=prefs.get("exam_format", "written"),
            course_name=prefs.get("course_name", ""),
            exam_type=prefs.get("exam_type", "final"),
            task_type=task_type,
            extra_instructions=prefs.get("extra_instructions", ""),
            workspace_id=session.workspace_id,
            # Files are already in the workspace from the preceding prepare_session
            # call (triggered by Apply / session load).  Skipping re-copy prevents
            # duplicate upload copies from accumulating on each generation request.
            copy_to_workspace=False,
            university_name=prefs.get("university_name", ""),
            major=prefs.get("major", ""),
            course_code=prefs.get("course_code", ""),
            professor_name=prefs.get("professor_name", ""),
            semester=prefs.get("semester", ""),
            exam_duration=prefs.get("exam_duration", ""),
            exam_info=prefs.get("exam_info", ""),
            workspace_folder=session.workspace_folder,
            progress_cb=progress_cb,
            effort_level=effort_level,
            language=language,
        )
        return md_path
