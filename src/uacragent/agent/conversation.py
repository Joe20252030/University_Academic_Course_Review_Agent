"""ConversationAgent — drives the chat loop and delegates task generation."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from uacragent.agent.session import AgentSession
from uacragent.domain.types import TaskType
from uacragent.infra.llm import LLMClient
from uacragent.infra.settings import Settings, get_settings


def _settings_for_session(base: Settings, session: AgentSession) -> Settings:
    """Return a Settings instance with provider/model overridden from the session."""
    import os
    overrides: dict = {}
    if session.llm_provider:
        overrides["LLM_PROVIDER"] = session.llm_provider
        os.environ["LLM_PROVIDER"] = session.llm_provider
    if session.llm_model:
        overrides["LLM_MODEL"] = session.llm_model
        os.environ["LLM_MODEL"] = session.llm_model
    if overrides:
        return Settings()   # re-read env (we just wrote to it)
    return base

_PROMPTS_DIR = Path(__file__).parent / "prompts"

# Regex that matches a [TASK:xxx] marker on its own line (optional trailing whitespace)
_TASK_MARKER_RE = re.compile(
    r"\[TASK:(review_summary|practice_booklet|mock_exam|exam_prediction)\]",
    re.IGNORECASE,
)


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

    def initialize_session(self, session: AgentSession) -> str:
        """Build the retriever from session files and attach it to *session*.

        Returns a short status message suitable for display in the chat window.
        Importing here to avoid circular imports between pipeline and agent.
        """
        from uacragent.agent.pipeline import AgentPipeline

        if not session.has_files():
            session.retriever = None
            return (
                "No documents are loaded yet. "
                "Add files in the Session Settings panel and click **Reload Session** to index them."
            )

        try:
            settings = _settings_for_session(self.settings, session)
            pipeline = AgentPipeline(settings)
            session.retriever = pipeline.prepare_session(session)
            n_types = len(session.active_files())
            n_files = sum(len(v) for v in session.active_files().values())
            return (
                f"Session ready. Indexed {n_files} file(s) across {n_types} document "
                f"type(s). You can now ask questions or request a study document."
            )
        except Exception as exc:  # noqa: BLE001
            session.retriever = None
            return f"Failed to initialise session: {exc}"

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    def chat(self, message: str, session: AgentSession) -> ChatResponse:
        """Process one user turn and return a :class:`ChatResponse`.

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
        context = self._retrieve_context(message, session)

        # -- 2. Build message list ---------------------------------------------
        system_content = self._render_system_prompt(session, context)
        messages: list = [SystemMessage(content=system_content)]
        messages.extend(session.chat_history)
        messages.append(HumanMessage(content=message))

        # -- 3. Call LLM (use session provider/model if different from default) --
        llm = LLMClient(_settings_for_session(self.settings, session))
        try:
            raw_response = llm.invoke(messages)
            assistant_text: str = getattr(raw_response, "content", str(raw_response))
        except Exception as exc:  # noqa: BLE001
            error_msg = f"LLM call failed: {exc}"
            return ChatResponse(text=error_msg, error=error_msg)

        # -- 4. Detect and strip task marker -----------------------------------
        task_type, clean_text = self._extract_task_marker(assistant_text)

        # -- 5. Run generation pipeline if task was requested ------------------
        output_path: str | None = None
        generation_error: str | None = None

        if task_type is not None:
            if not session.has_files():
                generation_error = (
                    "No documents are loaded. Please add files in the Session Settings "
                    "panel and reload the session before generating a document."
                )
            elif session.retriever is None:
                generation_error = (
                    "The session has not been initialised yet. "
                    "Click **Reload Session** to index your documents first."
                )
            else:
                try:
                    output_path = self._run_task(task_type, session)
                except Exception as exc:  # noqa: BLE001
                    generation_error = f"Generation failed: {exc}"

        # -- 6. Update history -------------------------------------------------
        session.chat_history.append(HumanMessage(content=message))
        session.chat_history.append(AIMessage(content=clean_text))
        session.trim_history()

        # -- 7. Build final reply text -----------------------------------------
        reply = clean_text
        if generation_error:
            reply += f"\n\n⚠️ {generation_error}"

        return ChatResponse(
            text=reply,
            output_path=output_path,
            task_type=task_type,
            error=generation_error,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _retrieve_context(self, message: str, session: AgentSession) -> str:
        """Return retrieved context text, or a placeholder if not available."""
        if session.retriever is None:
            return "*(No documents loaded — answers are based on general knowledge only.)*"
        try:
            docs = session.retriever.invoke(message)
            if not docs:
                return "*(No relevant excerpts found in the uploaded documents.)*"
            return "\n\n".join(d.page_content for d in docs)
        except Exception:  # noqa: BLE001
            return "*(Context retrieval failed — answers are based on general knowledge only.)*"

    def _render_system_prompt(self, session: AgentSession, context: str) -> str:
        """Fill the system prompt template with session values."""
        template = (_PROMPTS_DIR / "conversation_system.md").read_text(encoding="utf-8")

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
        )

    @staticmethod
    def _extract_task_marker(text: str) -> tuple[str | None, str]:
        """Return (task_type_value, cleaned_text) after stripping the marker."""
        match = _TASK_MARKER_RE.search(text)
        if match is None:
            return None, text.strip()

        task_value = match.group(1).lower()
        # Remove the entire marker line from the response
        clean = _TASK_MARKER_RE.sub("", text).strip()
        return task_value, clean

    def _run_task(self, task_type: str, session: AgentSession) -> str:
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
            copy_to_workspace=True,
            university_name=prefs.get("university_name", ""),
            major=prefs.get("major", ""),
            course_code=prefs.get("course_code", ""),
            professor_name=prefs.get("professor_name", ""),
            semester=prefs.get("semester", ""),
            exam_duration=prefs.get("exam_duration", ""),
            exam_info=prefs.get("exam_info", ""),
            workspace_folder=session.workspace_folder,
        )
        return md_path
