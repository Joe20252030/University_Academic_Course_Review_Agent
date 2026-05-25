"""Chat panel, send/receive, and document-indexing methods."""
from __future__ import annotations

import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from uacragent.agent.conversation import ConversationAgent, ChatResponse
from uacragent.agent.session import AgentSession
from uacragent.domain.providers import env_var_for, get_provider
from uacragent.domain.types import DocumentType, ExportFormat
from uacragent.export.docx import save_docx
from uacragent.export.pdf import save_pdf
from uacragent.infra.persistence import get_app_data_dir, save_session
from uacragent.infra.workspace import workspace_paths, ensure_workspace_dirs

from ._ui_constants import _strip_markdown, _open_file_in_os, _open_folder_in_os


class ChatMixin:
    """Mixin: chat send/receive, document indexing, and chat-display helpers."""
    def _get_agent(self) -> ConversationAgent:
        if self._agent is None:
            from uacragent.infra.settings import get_settings
            self._agent = ConversationAgent(get_settings())
        return self._agent

    # ------------------------------------------------------------------
    # Session list management
    # ------------------------------------------------------------------

    def _start_indexing(self, *, show_error_dialog: bool = True) -> None:
        """Index session documents in a background thread.

        *show_error_dialog* controls whether blocking error messageboxes are
        shown on failure.  Pass False for automatic triggers (sidebar select)
        so errors appear as inline chat messages instead.
        """
        if self._is_busy:
            return

        # ── Pre-flight checks ──────────────────────────────────────────
        # Check committed session state — do NOT read or inject live StringVars.
        # Apply is the only entry-point that commits settings to os.environ.
        provider = self._session.llm_provider or "gemini"
        env_var = env_var_for(provider)
        if not os.environ.get(env_var, "").strip():
            label = self._t(get_provider(provider).label_i18n_key)
            if show_error_dialog:
                messagebox.showwarning(
                    self._t("mb_api_key_title"),
                    self._t("mb_api_key_body").format(label=label, provider=provider))
            else:
                self._append_chat(
                    "system",
                    self._t("warn_no_api_key").format(label=label))
            return

        if not self._has_embedding_key():
            if show_error_dialog:
                messagebox.showwarning(
                    self._t("mb_embed_key_title"),
                    self._t("mb_embed_key_body"))
            else:
                self._append_chat("system", self._t("warn_no_embed_key"))
            return

        if not self._session.course_name:
            if show_error_dialog:
                messagebox.showwarning(
                    self._t("mb_course_name_title"),
                    self._t("mb_course_name_body"))
                self._open_settings()
            else:
                self._append_chat("system", self._t("warn_no_course"))
            return

        if not self._session.has_files():
            # No documents to index — wipe upload copies, the Chroma vector
            # store, and reset the indexed-files manifest so nothing stale lingers.
            from uacragent.agent.pipeline import (
                wipe_session_uploads, wipe_session_vectorstore)
            wipe_session_uploads(self._session)
            wipe_session_vectorstore(self._session)
            self._append_chat("system", self._t("warn_no_docs"))
            return

        # ── Workspace assignment (once, then locked) ───────────────────
        if not self._session.workspace_folder:
            self._session.workspace_folder = (
                get_app_data_dir() / "sessions" / self._session.workspace_id
            )
            self._workspace_var.set(str(self._session.workspace_folder))
        self._workspace_committed = True

        # ── Confirm local model download ───────────────────────────────
        if not self._confirm_model_download():
            return

        # ── Start background indexing ──────────────────────────────────
        self._session.retriever = None

        if self._emb_provider_var.get() == "local" and not self._is_model_cached(
            self._local_model_var.get()
        ):
            busy_label = self._t("downloading_model")
        else:
            busy_label = self._t("indexing_docs")

        self._set_busy(True, busy_label)
        self._session_status_var.set(busy_label)
        self._append_chat("system", busy_label)

        _show_err = show_error_dialog
        # Capture agent, language, and session NOW on the main thread.
        # _get_agent() lazily constructs self._agent and _on_apply_settings may
        # set self._agent = None concurrently — capturing here is the only safe
        # approach (same pattern already used by _on_send).
        captured_agent = self._get_agent()
        captured_lang  = self._language_var.get()

        def _work() -> None:
            # Capture session at thread-start so a mid-flight session swap
            # (e.g. user clicks "New") cannot redirect this thread's writes.
            session = self._session
            def _progress(msg: str) -> None:
                if not self._cancel_event.is_set():
                    try:
                        self.after(
                            0,
                            lambda m=msg: (
                                self._show_thinking(m)
                                if self.winfo_exists() else None
                            ),
                        )
                        self.after(
                            0,
                            lambda m=msg: (
                                self._session_status_var.set(m)
                                if self.winfo_exists() else None
                            ),
                        )
                    except tk.TclError:
                        pass  # window destroyed before after() was queued

            try:
                agent = captured_agent
                # force_reindex=True: Apply always runs the full pipeline so
                # changes to files, embedding provider, or model take effect.
                msg, _ = agent.initialize_session(
                    session, progress_cb=_progress,
                    force_reindex=True, language=captured_lang)
                if not self._cancel_event.is_set():
                    self.after(0, lambda m=msg, s=session: self._on_session_loaded(m, s))
            except Exception as exc:
                if not self._cancel_event.is_set():
                    self.after(
                        0,
                        lambda e=str(exc), s=session:
                            self._on_session_load_error(e, s, _show_err),
                    )

        threading.Thread(target=_work, daemon=True).start()

    def _attach_session_async(self) -> None:
        """Attach a retriever to the current session after a sidebar-select.

        Tries the fast path (open existing ChromaDB, zero API calls) first.
        Falls back to full indexing only when the database is absent or the
        file set has changed.

        Unlike _start_indexing (the Apply path) this method does NOT add a
        chat message when the fast path succeeds — the session is silently
        ready.  A completion notice is only shown when actual indexing ran.
        """
        if self._is_busy:
            return

        # ── Pre-flight (always inline — sidebar selects never show dialogs) ──
        provider = self._session.llm_provider or "gemini"
        env_var = env_var_for(provider)
        if not os.environ.get(env_var, "").strip():
            label = self._t(get_provider(provider).label_i18n_key)
            self._append_chat(
                "system",
                self._t("warn_no_api_key").format(label=label))
            return

        if not self._has_embedding_key():
            self._append_chat("system", self._t("warn_no_embed_key"))
            return

        if not self._session.course_name:
            self._append_chat("system", self._t("warn_no_course"))
            return

        if not self._session.has_files():
            self._append_chat("system", self._t("warn_no_docs"))
            return

        # Workspace is already committed for any loaded session.
        if not self._session.workspace_folder:
            self._session.workspace_folder = (
                get_app_data_dir() / "sessions" / self._session.workspace_id
            )
            self._workspace_var.set(str(self._session.workspace_folder))
        self._workspace_committed = True

        if not self._confirm_model_download():
            return

        loading_label = self._t("loading_session")
        self._set_busy(True, loading_label)
        self._session_status_var.set(loading_label)
        self._session.retriever = None
        # Capture agent and language NOW on the main thread (same TOCTOU fix
        # as _start_indexing and _on_send — avoids _get_agent() race with
        # _on_apply_settings resetting self._agent).
        captured_agent = self._get_agent()
        captured_lang  = self._language_var.get()

        def _work() -> None:
            # Capture session at thread-start so a mid-flight session swap
            # cannot redirect this thread's writes to the wrong session.
            session = self._session
            def _progress(msg: str) -> None:
                if not self._cancel_event.is_set():
                    try:
                        self.after(
                            0,
                            lambda m=msg: (
                                self._show_thinking(m)
                                if self.winfo_exists() else None
                            ),
                        )
                        self.after(
                            0,
                            lambda m=msg: (
                                self._session_status_var.set(m)
                                if self.winfo_exists() else None
                            ),
                        )
                    except tk.TclError:
                        pass  # window destroyed before after() was queued

            try:
                agent = captured_agent
                # force_reindex=False: use fast path when Chroma is current.
                status, was_cached = agent.initialize_session(
                    session, progress_cb=_progress, language=captured_lang)
                if not self._cancel_event.is_set():
                    self.after(
                        0,
                        lambda s=status, c=was_cached, sess=session:
                            self._on_attach_done(s, c, sess),
                    )
            except Exception as exc:  # noqa: BLE001
                if not self._cancel_event.is_set():
                    self.after(
                        0,
                        lambda e=str(exc), s=session:
                            self._on_session_load_error(e, s, False),
                    )

        threading.Thread(target=_work, daemon=True).start()

    def _on_attach_done(self, status: str, was_cached: bool, session: object) -> None:
        """Completion handler for _attach_session_async."""
        # Always release the busy lock so the UI is never permanently stuck.
        self._set_busy(False)
        # Discard stale results if the user switched to a different session
        # while this background thread was running.
        if self._session is not session:
            return
        self._update_header()
        self._session_status_var.set(status)
        if self._settings_alive():
            self._settings_status_var.set(status)
        # Only add a chat notice when actual (re-)indexing was performed.
        # On the fast path the session is silently ready — no noise in chat.
        if not was_cached:
            self._append_chat("system", self._t("docs_indexed").format(status=status))
        # Skip saving when the fast path was used: the session was loaded from
        # disk unchanged, so re-writing it would only bump last_modified pointlessly.
        if not was_cached:
            self._save_current_session()
        self._refresh_session_list()

    def _on_session_loaded(self, status: str, session: object) -> None:
        """Completion handler for _start_indexing (the Apply path)."""
        # Always release the busy lock so the UI is never permanently stuck.
        self._set_busy(False)
        # Discard stale results if the user replaced the session mid-flight.
        if self._session is not session:
            return
        self._update_header()
        self._session_status_var.set(status)
        if self._settings_alive():
            self._settings_status_var.set(status)
        # History is already visible — just append the completion notice.
        self._append_chat("system", self._t("docs_indexed").format(status=status))
        self._save_current_session()
        self._refresh_session_list()

    def _on_session_load_error(
        self, error: str, session: object, show_dialog: bool = True
    ) -> None:
        # Always release the busy lock so the UI is never permanently stuck.
        self._set_busy(False)
        # Discard stale errors from a session that is no longer active.
        if self._session is not session:
            return
        self._session_status_var.set(self._t("error_status").format(error=error))
        self._append_chat("system", self._t("indexing_failed").format(error=error))
        if not show_dialog:
            return
        error_lower = error.lower()
        if any(k in error_lower for k in ("api key", "api_key", "invalid_argument",
                                           "authentication", "permission_denied",
                                           "unauthenticated")):
            detail = self._t("mb_indexing_api_detail")
        else:
            detail = self._t("mb_indexing_other_detail")
        messagebox.showerror(
            self._t("mb_indexing_failed_title"),
            self._t("mb_indexing_failed_body").format(error=error, detail=detail),
        )

    # ------------------------------------------------------------------
    # Chat send / receive
    # ------------------------------------------------------------------

    def _on_return_key(self, event: tk.Event) -> str:
        if not (event.state & 0x1):   # Shift not held
            self._on_send()
            return "break"
        return ""

    def _on_send(self) -> None:
        if self._is_busy:
            return
        message = self._input_text.get("1.0", tk.END).strip()
        if not message:
            return
        # Use the committed session state — do NOT read live StringVars here.
        # Settings only take effect after the user clicks Apply.
        provider = self._session.llm_provider or "gemini"
        env_var = env_var_for(provider)
        if not os.environ.get(env_var, "").strip():
            label = self._t(get_provider(provider).label_i18n_key)
            messagebox.showwarning(
                self._t("mb_api_key_title"),
                self._t("mb_api_key_send_body").format(label=label))
            return
        if not self._session.course_name:
            messagebox.showwarning(
                self._t("mb_course_name_title"),
                self._t("mb_course_name_send_body"))
            self._open_settings()
            return
        self._input_text.delete("1.0", tk.END)
        self._append_chat("user", message)
        self._set_busy(True, self._t("thinking"))

        # Capture export format, effort level, language, session, and agent NOW
        # — before the background thread runs — so that UI changes mid-flight
        # cannot affect which format/effort/language/settings are used (TOCTOU fix).
        # Capturing the agent here (main thread) avoids calling get_settings()
        # from the background thread while the main thread may be writing os.environ.
        export_fmt      = self._export_format_var.get()
        effort_level    = self._effort_var.get()
        captured_lang   = self._language_var.get()
        captured_session = self._session
        captured_agent   = self._get_agent()

        def _work() -> None:
            def _progress(msg: str) -> None:
                if not self._cancel_event.is_set():
                    try:
                        self.after(
                            0,
                            lambda m=msg: (
                                self._show_thinking(m)
                                if self.winfo_exists() else None
                            ),
                        )
                    except tk.TclError:
                        pass  # window destroyed before after() was queued

            try:
                response = captured_agent.chat(
                    message, captured_session,
                    progress_cb=_progress,
                    effort_level=effort_level,
                    language=captured_lang,
                )
                if self._cancel_event.is_set():
                    # The LLM finished but the user cancelled before the response
                    # was dispatched to the UI.  chat() already appended the turn
                    # (human + AI) to session.chat_history — undo it so the
                    # invisible response doesn't silently persist on disk.
                    # pop_last_turn() is atomic: it removes both messages under
                    # one lock, so the cancel can never leave a dangling human
                    # message without its AI reply.
                    captured_session.chat_history.pop_last_turn()
                else:
                    self.after(0, lambda r=response, f=export_fmt, s=captured_session:
                               self._on_chat_response(r, f, s))
            except Exception as exc:
                if not self._cancel_event.is_set():
                    self.after(0, lambda e=str(exc), s=captured_session:
                               self._on_chat_error(e, s))

        threading.Thread(target=_work, daemon=True).start()

    def _send_message(self, message: str) -> None:
        self._input_text.delete("1.0", tk.END)
        self._input_text.insert("1.0", message)
        self._on_send()

    def _on_chat_response(
        self, response: ChatResponse, export_fmt: str, session: object
    ) -> None:
        self._set_busy(False)
        # Discard the response if the user navigated to a different session
        # while this chat request was in flight (session A's reply must not
        # appear in session B's chat display).
        if self._session is not session:
            return
        self._append_chat("assistant", response.text)
        if response.output_path:
            self._append_output_link(response.output_path, response.task_type, export_fmt)
        self._save_current_session()

    def _on_chat_error(self, error: str, session: object) -> None:
        self._set_busy(False)
        # Same session-staleness guard as _on_chat_response.
        if self._session is not session:
            return
        self._append_chat("system", self._t("chat_error").format(error=error))
        error_lower = error.lower()
        if any(k in error_lower for k in ("api key", "api_key", "invalid_argument",
                                           "authentication", "permission_denied",
                                           "unauthenticated")):
            detail = self._t("mb_response_api_detail")
        else:
            detail = self._t("mb_response_other_detail")
        messagebox.showerror(
            self._t("mb_response_failed_title"),
            self._t("mb_response_failed_body").format(error=error, detail=detail),
        )

    # ------------------------------------------------------------------
    # Chat display helpers
    # ------------------------------------------------------------------

    def _clear_chat(self) -> None:
        self._chat_text.configure(state="normal")
        self._chat_text.delete("1.0", tk.END)
        self._chat_text.configure(state="disabled")

    def _show_idle(self) -> None:
        """Blank right panel shown at startup before any session is selected."""
        self._set_chat_active(False)

    def _show_welcome(self) -> None:
        self._append_chat("assistant", self._t("welcome_msg"))

    def _replay_chat_history(self) -> None:
        """Re-render saved messages into the chat display. No status hints — those
        come from the indexing flow that follows immediately after."""
        from langchain_core.messages import HumanMessage, AIMessage
        for msg in self._session.chat_history.snapshot():
            if isinstance(msg, HumanMessage):
                self._append_chat("user", msg.content)
            elif isinstance(msg, AIMessage):
                self._append_chat("assistant", msg.content)

    def _append_chat(self, role: str, text: str) -> None:
        self._chat_text.configure(state="normal")
        if role == "user":
            self._chat_text.insert(tk.END, self._t("chat_you") + "\n", "user_label")
            self._chat_text.insert(tk.END, text + "\n", "user_body")
        elif role == "assistant":
            self._chat_text.insert(tk.END, self._t("chat_assistant") + "\n", "assistant_label")
            display = _strip_markdown(text)
            self._chat_text.insert(tk.END, display + "\n", "assistant_body")
        else:
            self._chat_text.insert(tk.END, text + "\n", "system_body")
        self._chat_text.configure(state="disabled")
        self._chat_text.see(tk.END)

    def _append_output_link(
        self,
        output_path: str,
        task_type: str | None,
        export_fmt: str,
    ) -> None:
        label = task_type.replace("_", " ").title() if task_type else "Output"
        self._chat_text.configure(state="normal")
        self._chat_text.insert(tk.END, f"\n📄 {label} generated: ", "assistant_body")

        from ._ui_constants import _THEME_COLORS
        _c = _THEME_COLORS.get(self._color_mode_var.get(), _THEME_COLORS["light"])
        tag_file = f"link_{id(output_path)}"
        self._chat_text.tag_configure(
            tag_file, foreground=_c["link_fg"], underline=True)
        self._chat_text.tag_bind(tag_file, "<Button-1>",
                                 lambda _e, p=output_path: _open_file_in_os(p))
        self._chat_text.tag_bind(tag_file, "<Enter>",
                                 lambda _e: self._chat_text.configure(cursor="hand2"))
        self._chat_text.tag_bind(tag_file, "<Leave>",
                                 lambda _e: self._chat_text.configure(cursor=""))
        self._chat_text.insert(tk.END, Path(output_path).name, tag_file)

        self._chat_text.insert(tk.END, "  ", "assistant_body")
        tag_folder = f"folder_{id(output_path)}"
        self._chat_text.tag_configure(
            tag_folder, foreground=_c["link_folder_fg"], underline=True)
        self._chat_text.tag_bind(tag_folder, "<Button-1>",
                                 lambda _e, p=output_path: _open_folder_in_os(
                                     str(Path(p).parent)))
        self._chat_text.tag_bind(tag_folder, "<Enter>",
                                 lambda _e: self._chat_text.configure(cursor="hand2"))
        self._chat_text.tag_bind(tag_folder, "<Leave>",
                                 lambda _e: self._chat_text.configure(cursor=""))
        self._chat_text.insert(tk.END, "[Open folder]", tag_folder)

        # Optional extra-format export — run in a background thread so the UI
        # is not frozen while python-docx / fpdf2 write the file.
        # export_fmt was captured at send-time (not now) to avoid TOCTOU.
        if export_fmt != ExportFormat.markdown.value and output_path.endswith(".md"):
            # Insert a placeholder that will be replaced once the export finishes.
            placeholder_tag = f"export_placeholder_{id(output_path)}"
            self._chat_text.insert(
                tk.END, f"\n⏳ Exporting {export_fmt.upper()}…", placeholder_tag)

            _ws_id     = self._session.workspace_id
            _ws_folder = self._session.workspace_folder

            def _export_worker() -> None:
                try:
                    ws = workspace_paths(workspace_id=_ws_id, workspace_folder=_ws_folder)
                    ensure_workspace_dirs(ws)
                    md_text = Path(output_path).read_text(encoding="utf-8")
                    extra_path = (save_docx(md_text, ws)
                                  if export_fmt == ExportFormat.docx.value
                                  else save_pdf(md_text, ws))
                    try:
                        self.after(0, lambda p=extra_path: _finish_export(p, None))
                    except tk.TclError:
                        pass  # window destroyed before export completed
                except Exception as exc:  # noqa: BLE001
                    try:
                        self.after(0, lambda e=str(exc): _finish_export(None, e))
                    except tk.TclError:
                        pass  # window destroyed before export completed

            def _finish_export(extra_path: str | None, error: str | None) -> None:
                """Replace the placeholder with the final link or error text."""
                try:
                    # Locate and delete the placeholder text.
                    start = self._chat_text.tag_ranges(placeholder_tag)
                    if start:
                        self._chat_text.configure(state="normal")
                        self._chat_text.delete(start[0], start[1])
                        if extra_path:
                            xtag = f"extra_{id(extra_path)}"
                            self._chat_text.tag_configure(
                                xtag, foreground="#1565c0", underline=True)
                            self._chat_text.tag_bind(
                                xtag, "<Button-1>",
                                lambda _e, p=extra_path: _open_file_in_os(p))
                            self._chat_text.insert(
                                start[0],
                                f"\n📥 {export_fmt.upper()} export: {Path(extra_path).name}",
                                xtag)
                        else:
                            self._chat_text.insert(
                                start[0], f"\n⚠️ Export failed: {error}", "system_body")
                        self._chat_text.configure(state="disabled")
                        self._chat_text.see(tk.END)
                except tk.TclError:
                    pass  # widget already destroyed

            threading.Thread(target=_export_worker, daemon=True).start()

        self._chat_text.insert(tk.END, "\n", "assistant_body")
        self._chat_text.configure(state="disabled")
        self._chat_text.see(tk.END)

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def _update_header(self) -> None:
        name = self._session.course_name or self._t("untitled_session")
        parts = [p for p in (self._session.course_code, self._session.semester) if p]
        self._header_course_var.set(f"{name}  ({', '.join(parts)})" if parts else name)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_current_session(self) -> None:
        # Do NOT call _sync_session_from_vars() here.
        # The session object always holds the last-committed state (set by
        # _on_apply_settings).  Syncing from live StringVars would allow
        # uncommitted settings to leak into the saved file silently.

        # Only persist sessions that have been formally committed (Apply was
        # clicked at least once, locking the workspace).  This prevents a blank
        # or file-less new session from silently appearing in the sidebar just
        # because the user typed a chat message before setting anything up.
        if not self._workspace_committed:
            return

        ui_extras = {
            "export_format":       self._export_format_var.get(),
            "embedding_provider":  self._emb_provider_var.get(),
            "local_embedding_model": self._local_model_var.get(),
        }
        save_session(self._session, ui_extras)


    def _on_cancel(self) -> None:
        """Signal the in-flight background request to be discarded."""
        self._cancel_event.set()
        self._set_busy(False)
        self._append_chat("system", self._t("request_cancelled"))
