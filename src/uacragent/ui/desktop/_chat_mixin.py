"""Chat panel, send/receive, and document-indexing methods."""
from __future__ import annotations

import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

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

    # ------------------------------------------------------------------
    # Provider capability checks
    # ------------------------------------------------------------------

    def _provider_supports_search(self) -> bool:
        return get_provider(self._session.llm_provider or "gemini").supports_search

    def _provider_supports_files(self) -> bool:
        return get_provider(self._session.llm_provider or "gemini").supports_files

    def _update_tool_btns(self) -> None:
        """Enable/disable search and upload buttons based on active provider capabilities."""
        can_search = self._provider_supports_search()
        can_files  = self._provider_supports_files()
        try:
            self._search_btn.set_state(can_search)
        except Exception:
            pass
        try:
            self._upload_btn.set_state(can_files)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Search toggle
    # ------------------------------------------------------------------

    def _toggle_search(self) -> None:
        if not self._provider_supports_search():
            self._append_chat("system", self._t("search_unsupported"))
            return
        self._search_active = not self._search_active
        self._refresh_search_btn()
        # Rebuild the strip so the "🌐 Web search ON" chip appears/disappears
        self._rebuild_attach_strip()

    def _refresh_search_btn(self) -> None:
        """Update search button visual state and base colours for current theme.

        Inactive: qa_bg chip fill (visible against input_bg).
        Active:   btn_primary_bg (gold) to show search is on for the next send.
        """
        from ._ui_constants import _THEME_COLORS
        mode = self._color_mode_var.get() if hasattr(self, "_color_mode_var") else "light"
        c = _THEME_COLORS.get(mode, _THEME_COLORS["light"])
        _tbg  = c.get("qa_bg", "#edf0f8")
        _tfg  = c.get("qa_fg", c["input_fg"])
        _thov = c.get("qa_bg_hover", "#dce3f2")
        _pbg = c.get("input_bg", "#f5f7fb")
        try:
            if self._search_active:
                self._search_btn.update_style(
                    chip_bg=c.get("btn_primary_bg", "#f5a623"),
                    chip_fg=c.get("btn_primary_fg", "#1a2744"),
                    hover_bg=c.get("btn_primary_hover", "#e8961a"),
                    parent_bg=_pbg,
                )
            else:
                self._search_btn.update_style(
                    chip_bg=_tbg, chip_fg=_tfg, hover_bg=_thov,
                    parent_bg=_pbg,
                )
        except Exception:
            pass
        # Keep upload button colours in sync with theme too
        try:
            self._upload_btn.update_style(
                chip_bg=_tbg, chip_fg=_tfg, hover_bg=_thov,
                parent_bg=_pbg,
            )
        except Exception:
            pass
        # Rebuild the strip so the search chip colour matches the new theme
        try:
            self._rebuild_attach_strip()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # File attachment
    # ------------------------------------------------------------------

    def _pick_files(self) -> None:
        if not self._provider_supports_files():
            return
        from tkinter import filedialog
        paths = filedialog.askopenfilenames(
            title=self._t("attach_files_title"),
            filetypes=[
                (self._t("attach_supported"), "*.png *.jpg *.jpeg *.gif *.webp *.bmp *.pdf *.docx *.txt *.md *.py *.csv *.json *.xml *.html"),
                (self._t("attach_images"),    "*.png *.jpg *.jpeg *.gif *.webp *.bmp"),
                (self._t("attach_docs"),      "*.pdf *.docx"),
                (self._t("attach_text"),      "*.txt *.md *.py *.csv *.json"),
                (self._t("attach_all"),       "*.*"),
            ],
        )
        from uacragent.agent.conversation import _MIME_MAP
        for p in paths:
            suffix = Path(p).suffix.lower()
            mime = _MIME_MAP.get(suffix, "application/octet-stream")
            self._pending_attachments.append({
                "path": p,
                "name": Path(p).name,
                "mime": mime,
            })
        if paths:
            self._rebuild_attach_strip()

    def _remove_attachment(self, idx: int) -> None:
        if 0 <= idx < len(self._pending_attachments):
            self._pending_attachments.pop(idx)
        self._rebuild_attach_strip()

    def _rebuild_attach_strip(self) -> None:
        """Rebuild the attachment / search-state chip strip above the input field.

        The strip is visible whenever:
        * one or more files are pending attachment, OR
        * web search is toggled ON for the next send.

        All chips use _RoundedChip for consistent rounded styling.
        Clicking anywhere on a chip removes the file / turns off search.
        """
        from ._custom_widgets import _RoundedChip
        from ._ui_constants import _THEME_COLORS

        strip = self._attach_strip
        for w in strip.winfo_children():
            w.destroy()

        _search_on = getattr(self, "_search_active", False)

        if not self._pending_attachments and not _search_on:
            try:
                strip.grid_remove()
            except Exception:
                pass
            return

        # Show the strip
        strip.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 4))
        mode    = self._color_mode_var.get() if hasattr(self, "_color_mode_var") else "light"
        c       = _THEME_COLORS.get(mode, _THEME_COLORS["light"])
        pbg     = c.get("input_bg",       "#ffffff")   # strip/parent background
        chip_bg = c.get("qa_bg",          "#edf0f8")
        chip_fg = c.get("input_fg",       "#1a2744")
        hov_bg  = c.get("qa_bg_hover",    "#dce3f2")

        # ── Web-search indicator chip ─────────────────────────────────────────
        if _search_on:
            _sbg  = c.get("btn_primary_bg",    "#f5a623")
            _sfg  = c.get("btn_primary_fg",    "#1a2744")
            _shov = c.get("btn_primary_hover", "#e8961a")

            def _turn_off(_e=None):
                if getattr(self, "_search_active", False):
                    self._toggle_search()

            _RoundedChip(
                strip,
                text="🌐  Web search ON  ×",
                chip_bg=_sbg, chip_fg=_sfg,
                parent_bg=pbg,
                font=("TkDefaultFont", 10, "bold"),
                padx=10, pady=4,
                hover_bg=_shov,
                command=_turn_off,
            ).pack(side="left", padx=(0, 6), pady=2)

        # ── File attachment chips ─────────────────────────────────────────────
        for idx, att in enumerate(self._pending_attachments):
            mime = att.get("mime", "")
            if mime.startswith("image/"):
                icon = "🖼"
            elif mime == "application/pdf":
                icon = "📄"
            else:
                icon = "📎"

            name = att["name"]
            if len(name) > 20:
                name = name[:9] + "…" + name[-8:]

            _RoundedChip(
                strip,
                text=f"{icon}  {name}  ×",
                chip_bg=chip_bg, chip_fg=chip_fg,
                parent_bg=pbg,
                font=("TkDefaultFont", 10),
                padx=10, pady=4,
                hover_bg=hov_bg,
                command=lambda i=idx: self._remove_attachment(i),
            ).pack(side="left", padx=(0, 4), pady=2)

    # ------------------------------------------------------------------
    # Drag-and-drop file support
    # ------------------------------------------------------------------

    def _setup_drag_drop(self) -> None:
        """Bind tkinterdnd2 drop events to the chat canvas area.

        Safe no-op when tkinterdnd2 is not installed or the Tk extension is
        unavailable — the app works normally without drag-and-drop in that case.

        ## Why we register on every widget in the chat area

        tkdnd routes DnD events to the *topmost* widget under the cursor.
        On macOS (Cocoa DnD), tkdnd does NOT walk up to the nearest registered
        ancestor — if the topmost widget is unregistered the event is silently
        discarded.  We use a two-layer strategy:

        Layer 1 — Static targets: root window + ``_msg_canvas`` + ``_msg_frame``
          + ``_dnd_overlay``.  These cover the empty canvas area below all
          messages and the overlay itself.

        Layer 2 — Dynamic targets: every widget created inside a message bubble
          (``_append_chat_user``, ``_append_chat_assistant``, system labels)
          calls ``_dnd_register(widget)`` when it is created.  This ensures that
          no matter which ``tk.Label`` or ``tk.Frame`` is topmost under the
          cursor, it is always a registered drop target.

        ## Correct event names for drop targets

        tkdnd distinguishes drag-SOURCE events from drop-TARGET events:
          - Drop target: ``<<DropEnter>>``, ``<<DropPosition>>``,
                         ``<<DropLeave>>``, ``<<Drop>>``
          - Drag source: ``<<DragInitCmd>>``, ``<<DragEndCmd>>``

        The previous code mistakenly bound ``<<DragEnter>>`` / ``<<DragLeave>>``
        (drag-source events) — those never fire on a drop target, so the overlay
        never appeared and the whole DnD flow silently failed.

        ## Return values

        ``<<DropEnter>>``, ``<<DropPosition>>``, and ``<<Drop>>`` callbacks must
        return an action string (``"copy"``, ``"refuse_drop"``, etc.) so the OS
        updates the cursor correctly.  ``<<DropLeave>>`` needs no return value.
        """
        try:
            from tkinterdnd2 import DND_FILES as _DND_FILES
        except Exception:
            return  # tkinterdnd2 not installed

        # Store so _dnd_register() can use it without a repeated import.
        self._dnd_files_type = _DND_FILES

        # Layer 1: static targets — root window, message canvas/frame, overlay.
        root = self.winfo_toplevel()
        _targets: list = [root]
        for attr in ("_msg_canvas", "_msg_frame", "_dnd_overlay"):
            if hasattr(self, attr):
                _targets.append(getattr(self, attr))

        for widget in _targets:
            self._dnd_register(widget)

    def _dnd_register(self, widget) -> None:
        """Register *widget* as a DnD drop target for files.

        Safe no-op when ``_setup_drag_drop`` has not run yet (i.e. tkinterdnd2
        is unavailable) — callers need not guard with ``hasattr`` checks.
        """
        _dnd_files_type = getattr(self, "_dnd_files_type", None)
        if _dnd_files_type is None:
            return
        try:
            widget.drop_target_register(_dnd_files_type)
            widget.dnd_bind("<<Drop>>",         self._on_dnd_drop)
            widget.dnd_bind("<<DropEnter>>",    self._on_dnd_enter)
            widget.dnd_bind("<<DropPosition>>", self._on_dnd_position)
            widget.dnd_bind("<<DropLeave>>",    self._on_dnd_leave)
        except Exception:
            pass

    @staticmethod
    def _parse_dnd_paths(raw: str) -> list[str]:
        """Parse tkinterdnd2 path data into individual file paths.

        tkinterdnd2 returns paths space-separated; paths containing spaces are
        wrapped in braces:  ``{/path/with spaces/file.pdf} /simple/path.png``
        """
        paths: list[str] = []
        raw = raw.strip()
        while raw:
            if raw.startswith("{"):
                end = raw.find("}")
                if end == -1:
                    break
                paths.append(raw[1:end])
                raw = raw[end + 1:].strip()
            else:
                parts = raw.split(None, 1)
                paths.append(parts[0])
                raw = parts[1].strip() if len(parts) > 1 else ""
        return [p for p in paths if p]

    def _is_over_chat_area(self, event) -> bool:
        """Return True when the drag/drop cursor is inside the message canvas.

        Uses ``event.x_root`` / ``event.y_root`` (screen coordinates provided
        by tkinterdnd2) to compare against the message canvas screen position.
        Falls back to False on any error so callers can degrade gracefully.
        """
        try:
            x, y = event.x_root, event.y_root
            cv   = self._msg_canvas
            cx, cy = cv.winfo_rootx(), cv.winfo_rooty()
            return cx <= x <= cx + cv.winfo_width() and cy <= y <= cy + cv.winfo_height()
        except Exception:
            return False

    def _on_dnd_enter(self, event) -> str:
        """``<<DropEnter>>`` — drag entered the root window.

        Show the overlay only when the cursor is already over the chat area;
        ``<<DropPosition>>`` will update visibility as the cursor moves.
        Must return an action string so the OS shows the correct cursor.
        """
        if self._is_over_chat_area(event):
            self._show_dnd_overlay()
            return "copy"
        return "refuse_drop"

    def _on_dnd_position(self, event) -> str:
        """``<<DropPosition>>`` — cursor moved while dragging over the window.

        Shows/hides the overlay as the cursor crosses the chat-area boundary
        and returns ``"copy"`` / ``"refuse_drop"`` to update the OS cursor.
        """
        if self._is_over_chat_area(event):
            self._show_dnd_overlay()
            return "copy"
        self._hide_dnd_overlay()
        return "refuse_drop"

    def _on_dnd_leave(self, event) -> None:
        """``<<DropLeave>>`` — drag left the root window entirely."""
        self._hide_dnd_overlay()

    def _on_dnd_drop(self, event) -> str:
        """``<<Drop>>`` — files dropped; process only when over the chat area."""
        self._hide_dnd_overlay()

        if not self._is_over_chat_area(event):
            return "refuse_drop"

        if not self._provider_supports_files():
            self._append_chat("system", self._t("files_unsupported"))
            return "refuse_drop"

        from uacragent.agent.conversation import _MIME_MAP
        paths = self._parse_dnd_paths(getattr(event, "data", "") or "")
        added = 0
        for p in paths:
            suffix = Path(p).suffix.lower()
            mime = _MIME_MAP.get(suffix, "application/octet-stream")
            self._pending_attachments.append({
                "path": p,
                "name": Path(p).name,
                "mime": mime,
            })
            added += 1

        if added:
            self._rebuild_attach_strip()

        return "copy"

    def _show_dnd_overlay(self) -> None:
        """Show the drop overlay that covers the message canvas."""
        try:
            from ._ui_constants import _THEME_COLORS
            mode = self._color_mode_var.get() if hasattr(self, "_color_mode_var") else "light"
            c = _THEME_COLORS.get(mode, _THEME_COLORS["light"])
            _dnd_bg = c.get("qa_bg", "#edf0f8")
            _dnd_fg = c.get("text_fg", "#1a2744")
            _dnd_ac = c.get("btn_primary_bg", "#f5a623")
            self._dnd_overlay.configure(bg=_dnd_bg, highlightbackground=_dnd_ac)
            self._dnd_overlay_lbl.configure(
                text=self._t("dnd_drop_label"),
                bg=_dnd_bg, fg=_dnd_fg,
            )
            self._dnd_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
            self._dnd_overlay.lift()
        except Exception:
            pass

    def _hide_dnd_overlay(self) -> None:
        """Hide the drop overlay."""
        try:
            self._dnd_overlay.place_forget()
        except Exception:
            pass

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
                self._show_info_dialog(
                    self._t("mb_api_key_title"),
                    self._t("mb_api_key_body").format(label=label, provider=provider))
            else:
                self._append_chat(
                    "system",
                    self._t("warn_no_api_key").format(label=label))
            return

        if not self._session.course_name:
            if show_error_dialog:
                self._show_info_dialog(
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

        self._set_busy(True, busy_label, mode="index")
        self._session_status_var.set(busy_label)
        # Mirror the busy label in the settings dialog status bar (if open) so
        # it always shows what is actually happening, not a stale prior message.
        if self._settings_alive():
            try:
                self._settings_status_var.set(busy_label)
            except tk.TclError:
                pass
        self._append_chat("system", busy_label)

        _show_err = show_error_dialog
        # Capture agent, language, session, and request token on the main thread.
        # The token lets callbacks self-discard when the user cancels between the
        # cancel-check and the after() post (TOCTOU race elimination).
        captured_agent = self._get_agent()
        captured_lang  = self._language_var.get()
        captured_token = self._request_token

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
                # force_reindex=False: let the manifest decide whether re-indexing
                # is actually needed.  The fast path is taken when the file set,
                # embedding provider, and model all match what was last indexed —
                # avoiding redundant embedding API calls when only non-index
                # settings (course name, exam format, LLM provider, etc.) changed.
                msg, cached, warn = agent.initialize_session(
                    session, progress_cb=_progress,
                    force_reindex=False, language=captured_lang)
                if not self._cancel_event.is_set():
                    self.after(0, lambda m=msg, c=cached, w=warn, s=session, t=captured_token:
                               self._request_token == t and
                               self._on_session_loaded(m, s, was_cached=c, fast_path_warning=w))
                else:
                    # Cancel was requested while the operation was running.
                    # The completion handler won't be called, so we must release
                    # the busy lock here after the thread has actually finished.
                    self.after(0, lambda: self._set_busy(False))
            except Exception as exc:
                if not self._cancel_event.is_set():
                    self.after(
                        0,
                        lambda e=str(exc), s=session, t=captured_token:
                            self._request_token == t and
                            self._on_session_load_error(e, s, _show_err),
                    )
                else:
                    # Cancelled; release busy lock from the thread's finally path.
                    self.after(0, lambda: self._set_busy(False))

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
        self._set_busy(True, loading_label, mode="index")
        self._session_status_var.set(loading_label)
        self._session.retriever = None
        captured_agent = self._get_agent()
        captured_lang  = self._language_var.get()
        captured_token = self._request_token

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
                status, was_cached, warn = agent.initialize_session(
                    session, progress_cb=_progress, language=captured_lang)
                if not self._cancel_event.is_set():
                    self.after(
                        0,
                        lambda s=status, c=was_cached, w=warn, sess=session, t=captured_token:
                            self._request_token == t and
                            self._on_attach_done(s, c, sess, fast_path_warning=w),
                    )
                else:
                    # Cancel was requested; release busy lock from thread's finally path.
                    self.after(0, lambda: self._set_busy(False))
            except Exception as exc:  # noqa: BLE001
                if not self._cancel_event.is_set():
                    self.after(
                        0,
                        lambda e=str(exc), s=session, t=captured_token:
                            self._request_token == t and
                            self._on_session_load_error(e, s, False),
                    )
                else:
                    # Cancelled; release busy lock from thread's finally path.
                    self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=_work, daemon=True).start()

    def _on_attach_done(
        self, status: str, was_cached: bool, session: object,
        fast_path_warning: str | None = None,
    ) -> None:
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
        # Show fast-path failure indicator before the completion notice.
        if fast_path_warning:
            self._append_chat("system", fast_path_warning)
        # Only add a chat notice when actual (re-)indexing was performed.
        # On the fast path the session is silently ready — no noise in chat.
        if not was_cached:
            self._append_chat("system", self._t("docs_indexed").format(status=status))
        # Skip saving when the fast path was used: the session was loaded from
        # disk unchanged, so re-writing it would only bump last_modified pointlessly.
        if not was_cached:
            self._save_current_session()
        self._refresh_session_list()

    def _on_session_loaded(
        self, status: str, session: object,
        was_cached: bool = False,
        fast_path_warning: str | None = None,
    ) -> None:
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
        # Show fast-path failure indicator before the completion notice.
        if fast_path_warning:
            self._append_chat("system", fast_path_warning)
        # When the fast path was used (nothing index-relevant changed), show a
        # lighter "settings saved" notice instead of "documents indexed".
        if was_cached:
            self._append_chat("system", self._t("settings_saved_cached"))
        else:
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
        _err_status = self._t("error_status").format(error=error)
        self._session_status_var.set(_err_status)
        # Mirror the error in the settings dialog status bar so it never gets
        # stuck on "Applying settings and re-indexing…" after a failure.
        if self._settings_alive():
            try:
                self._settings_status_var.set(_err_status)
            except tk.TclError:
                pass
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
        self._show_info_dialog(
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
        # Capture and clear attachments/search state before any thread starts
        captured_attachments = list(self._pending_attachments)
        captured_search      = self._search_active
        self._pending_attachments.clear()
        self._search_active = False
        self._rebuild_attach_strip()
        self._refresh_search_btn()
        # Use the committed session state — do NOT read live StringVars here.
        # Settings only take effect after the user clicks Apply.
        provider = self._session.llm_provider or "gemini"
        env_var = env_var_for(provider)
        if not os.environ.get(env_var, "").strip():
            label = self._t(get_provider(provider).label_i18n_key)
            self._show_info_dialog(
                self._t("mb_api_key_title"),
                self._t("mb_api_key_send_body").format(label=label))
            return
        if not self._session.course_name:
            self._show_info_dialog(
                self._t("mb_course_name_title"),
                self._t("mb_course_name_send_body"))
            self._open_settings()
            return
        self._input_text.delete("1.0", tk.END)
        self._append_chat("user", message)
        self._set_busy(True, self._t("thinking"))

        # Capture export format, effort level, reasoning mode, language, session,
        # and agent NOW — before the background thread runs — so that UI changes
        # mid-flight cannot affect which settings are used (TOCTOU fix).
        # Capturing the agent here (main thread) avoids calling get_settings()
        # from the background thread while the main thread may be writing os.environ.
        export_fmt       = self._export_format_var.get()
        effort_level     = self._effort_var.get()
        reasoning_mode   = (
            self._reasoning_mode_var.get()
            if hasattr(self, "_reasoning_mode_var")
            else "quick"
        )
        captured_lang    = self._language_var.get()
        captured_session = self._session
        captured_agent   = self._get_agent()
        captured_token   = self._request_token

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
                    reasoning_mode=reasoning_mode,
                    language=captured_lang,
                    search_enabled=captured_search,
                    attachments=captured_attachments,
                )
                if self._cancel_event.is_set() or self._request_token != captured_token:
                    # The LLM finished but the user cancelled before the response
                    # was dispatched to the UI (or a new operation started).
                    # chat() already appended the turn (human + AI) to
                    # session.chat_history — undo it so the invisible response
                    # doesn't silently persist on disk.
                    captured_session.chat_history.pop_last_turn()
                    # Release busy lock since the completion handler won't run.
                    self.after(0, lambda: self._set_busy(False))
                else:
                    self.after(0, lambda r=response, f=export_fmt, s=captured_session:
                               self._on_chat_response(r, f, s))
            except Exception as exc:
                if not self._cancel_event.is_set() and self._request_token == captured_token:
                    self.after(0, lambda e=str(exc), s=captured_session:
                               self._on_chat_error(e, s))
                else:
                    # Cancelled; release busy lock from thread's finally path.
                    self.after(0, lambda: self._set_busy(False))

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
        self._show_info_dialog(
            self._t("mb_response_failed_title"),
            self._t("mb_response_failed_body").format(error=error, detail=detail),
        )

    # ------------------------------------------------------------------
    # Chat display helpers
    # ------------------------------------------------------------------

    def _clear_chat(self) -> None:
        """Destroy all message bubble widgets and reset scroll position."""
        if hasattr(self, "_msg_frame"):
            for w in list(self._msg_frame.winfo_children()):
                try:
                    w.destroy()
                except Exception:
                    pass
            try:
                self._msg_canvas.configure(scrollregion=(0, 0, 0, 0))
            except Exception:
                pass
        self._last_assistant_content = None
        self._thinking_lbl = None

    def _show_idle(self) -> None:
        """Blank right panel shown at startup before any session is selected."""
        self._set_chat_active(False)

    def _show_welcome(self) -> None:
        self._append_chat("assistant", self._t("welcome_msg"))

    @staticmethod
    def _content_to_str(content) -> str:
        """Convert a LangChain message content value to a plain string.

        ``content`` is normally a ``str``, but multimodal messages may use a
        ``list`` of content parts (e.g. ``[{"type": "text", "text": "..."},
        {"type": "image_url", ...}]``).  This helper extracts and joins the
        text parts so the chat display always receives a flat string.
        """
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict) and part.get("type") == "text":
                    parts.append(part.get("text", ""))
            return " ".join(parts).strip()
        return str(content)

    def _replay_chat_history(self) -> None:
        """Re-render saved messages into the chat display. No status hints — those
        come from the indexing flow that follows immediately after."""
        from langchain_core.messages import HumanMessage, AIMessage
        for msg in self._session.chat_history.snapshot():
            if isinstance(msg, HumanMessage):
                self._append_chat("user", self._content_to_str(msg.content))
            elif isinstance(msg, AIMessage):
                self._append_chat("assistant", self._content_to_str(msg.content))

    def _append_chat(self, role: str, text: str) -> None:
        """Append a flat message widget to the chat scroll area."""
        if not hasattr(self, "_msg_frame"):
            return

        from ._ui_constants import _THEME_COLORS

        _mode = self._color_mode_var.get() if hasattr(self, "_color_mode_var") else "light"
        c = _THEME_COLORS.get(_mode, _THEME_COLORS["light"])
        card_bg = c.get("text_bg", "#ffffff")
        sz = self._font_size() if hasattr(self, "_font_size") else 13
        _H_PAD  = 12  # horizontal padding inside message area
        _V_PAD  = 7   # vertical padding inside message area

        # ── System messages: no bubble, just italic dimmed selectable text ──
        if role == "system":
            sys_text = tk.Text(
                self._msg_frame,
                wrap="word",
                relief="flat", bd=0, highlightthickness=0,
                bg=card_bg,
                fg=c.get("status_fg", "#6b7280"),
                font=("TkDefaultFont", max(sz - 1, 10), "italic"),
                padx=20, pady=5,
                cursor="ibeam",
                height=1,
            )
            sys_text.insert("1.0", text)
            sys_text.configure(
                state="disabled",
                selectbackground=c.get("lb_sel_bg",  "#1b3167"),
                selectforeground=c.get("lb_sel_fg",  "#ffffff"),
                inactiveselectbackground=c.get("lb_sel_bg", "#1b3167"),
            )
            sys_text.pack(fill="x", pady=(2, 2))

            def _sync_sys_height(_e=None, _w=sys_text):
                try:
                    _w.update_idletasks()
                    n = _w.count("1.0", "end", "displaylines")
                    if isinstance(n, tuple):
                        n = n[0] if n else 1
                    if n and n > 0:
                        new_h = max(1, n)
                        if int(str(_w.cget("height"))) != new_h:
                            _w.configure(height=new_h)
                except Exception:
                    pass

            sys_text.bind("<Configure>", _sync_sys_height)
            self._bind_chat_scroll(sys_text)
            self._dnd_register(sys_text)
            self._scroll_chat_to_bottom()
            return

        # ── User message: rounded box; Assistant: flat text, no box ─────────
        if role == "user":
            self._append_chat_user(c, card_bg, sz, text, _H_PAD, _V_PAD)
        else:
            self._append_chat_assistant(c, card_bg, sz, text, _H_PAD, _V_PAD)
        self._scroll_chat_to_bottom()

    def _append_chat_user(self, c, card_bg, sz, text, _H_PAD, _V_PAD) -> None:
        """Render a user message inside a rounded box."""
        from ._custom_widgets import draw_rounded_rect

        label_text = self._t("chat_you")
        bubble_bg  = c.get("user_bubble_bg",    "#e8f0fe")
        label_fg   = c.get("user_fg",           "#1b3167")
        body_fg    = c.get("user_fg",           "#1b3167")
        border_col = c.get("user_bubble_border", "#c5d5f0")
        _OFF = 4   # gap between canvas edge and inner frame (shows corner radius)
        r    = 10  # corner radius

        cv = tk.Canvas(self._msg_frame, bg=card_bg, highlightthickness=0, bd=0)
        cv.pack(fill="x", padx=_H_PAD, pady=(6, 2))

        shell = tk.Frame(cv, bg=bubble_bg)
        win_id = cv.create_window(_OFF, _OFF, window=shell, anchor="nw")

        role_lbl = tk.Label(
            shell, text=label_text,
            bg=bubble_bg, fg=label_fg,
            font=("TkDefaultFont", max(sz - 1, 10), "bold"),
            anchor="w", padx=_H_PAD, pady=_V_PAD,
        )
        role_lbl.pack(fill="x")

        # tk.Text in read-only mode: users can select and copy text with
        # standard keyboard shortcuts (Cmd+C / Ctrl+C) and mouse drag.
        body_text = tk.Text(
            shell,
            wrap="word",
            relief="flat", bd=0, highlightthickness=0,
            bg=bubble_bg, fg=body_fg,
            font=("TkDefaultFont", sz),
            padx=_H_PAD, pady=_V_PAD,
            cursor="ibeam",
            height=1,
        )
        body_text.insert("1.0", text)
        body_text.configure(
            state="disabled",
            selectbackground=c.get("lb_sel_bg",  "#1b3167"),
            selectforeground=c.get("lb_sel_fg",  "#ffffff"),
            inactiveselectbackground=c.get("lb_sel_bg", "#1b3167"),
        )
        body_text.pack(fill="x")

        def _sync_body_text_height(_e=None, _w=body_text):
            """Resize the text widget height to exactly fit its display lines.

            Guards against self-triggering Configure loops by only calling
            configure() when the computed height actually differs from the
            current height.
            """
            try:
                _w.update_idletasks()
                n = _w.count("1.0", "end", "displaylines")
                if isinstance(n, tuple):
                    n = n[0] if n else 1
                if n and n > 0:
                    new_h = max(1, n)
                    if int(str(_w.cget("height"))) != new_h:
                        _w.configure(height=new_h)
            except Exception:
                pass

        body_text.bind("<Configure>", _sync_body_text_height)

        def _draw(_r=r, _bg=bubble_bg, _bd=border_col):
            cv.delete("bb")
            w, h = cv.winfo_width(), cv.winfo_height()
            if w > 1 and h > 1:
                draw_rounded_rect(cv, 0, 0, w, h, r=_r,
                                  fill=_bg, outline="", tags="bb")
                draw_rounded_rect(cv, 1, 1, w - 1, h - 1, r=_r,
                                  fill="", outline=_bd, width=1, tags="bb")
                cv.tag_lower("bb")

        def _sync_width(e, _wid=win_id, _off=_OFF, _hp=_H_PAD):
            new_w = max(1, e.width - 2 * _off)
            cv.itemconfigure(_wid, width=new_w)

        def _sync_height(_e, _off=_OFF):
            req = shell.winfo_reqheight()
            new_h = req + 2 * _off
            if cv.winfo_height() != new_h:
                cv.configure(height=new_h)
            _draw()

        cv.bind("<Configure>",    lambda e: (_sync_width(e), _draw()))
        shell.bind("<Configure>", _sync_height)

        for w in (cv, shell, role_lbl, body_text):
            self._bind_chat_scroll(w)
            self._dnd_register(w)

    def _append_chat_assistant(self, c, card_bg, sz, text, _H_PAD, _V_PAD) -> None:
        """Render an assistant message as plain text — no bounding box."""
        text = _strip_markdown(text)
        label_text = self._t("chat_assistant")
        label_fg   = c.get("assist_fg",  "#b06000")
        body_fg    = c.get("assist_body", "#2d3748")

        shell = tk.Frame(self._msg_frame, bg=card_bg)
        shell.pack(fill="x", padx=_H_PAD, pady=(6, 2))

        role_lbl = tk.Label(
            shell, text=label_text,
            bg=card_bg, fg=label_fg,
            font=("TkDefaultFont", max(sz - 1, 10), "bold"),
            anchor="w", pady=_V_PAD,
        )
        role_lbl.pack(fill="x")

        # tk.Text in read-only mode: users can select and copy text with
        # standard keyboard shortcuts (Cmd+C / Ctrl+C) and mouse drag.
        body_text = tk.Text(
            shell,
            wrap="word",
            relief="flat", bd=0, highlightthickness=0,
            bg=card_bg, fg=body_fg,
            font=("TkDefaultFont", sz),
            padx=0, pady=_V_PAD,
            cursor="ibeam",
            height=1,
        )
        body_text.insert("1.0", text)
        body_text.configure(
            state="disabled",
            selectbackground=c.get("lb_sel_bg",  "#1b3167"),
            selectforeground=c.get("lb_sel_fg",  "#ffffff"),
            inactiveselectbackground=c.get("lb_sel_bg", "#1b3167"),
        )
        body_text.pack(fill="x")

        def _sync_body_text_height(_e=None, _w=body_text):
            """Resize the text widget height to exactly fit its display lines.

            Guards against self-triggering Configure loops by only calling
            configure() when the computed height actually differs.
            """
            try:
                _w.update_idletasks()
                n = _w.count("1.0", "end", "displaylines")
                if isinstance(n, tuple):
                    n = n[0] if n else 1
                if n and n > 0:
                    new_h = max(1, n)
                    if int(str(_w.cget("height"))) != new_h:
                        _w.configure(height=new_h)
            except Exception:
                pass

        body_text.bind("<Configure>", _sync_body_text_height)

        self._last_assistant_content   = shell
        self._last_assistant_bubble_bg = card_bg
        self._last_assistant_body_fg   = body_fg
        self._last_assistant_card_bg   = card_bg

        for w in (shell, role_lbl, body_text):
            self._bind_chat_scroll(w)
            self._dnd_register(w)

    def _append_output_link(
        self,
        output_path: str,
        task_type: str | None,
        export_fmt: str,
    ) -> None:
        """Append a file-link row inside the last assistant bubble."""
        shell = getattr(self, "_last_assistant_content", None)
        if shell is None or not shell.winfo_exists():
            return

        from ._ui_constants import _THEME_COLORS
        _mode = self._color_mode_var.get() if hasattr(self, "_color_mode_var") else "light"
        c = _THEME_COLORS.get(_mode, _THEME_COLORS["light"])
        bubble_bg = getattr(self, "_last_assistant_bubble_bg", c.get("asst_bubble_bg", "#fdf6ee"))
        body_fg   = getattr(self, "_last_assistant_body_fg",   c.get("assist_body",    "#2d3748"))
        sz = self._font_size() if hasattr(self, "_font_size") else 13

        label = task_type.replace("_", " ").title() if task_type else "Output"

        # ── Link row ──────────────────────────────────────────────────────
        link_row = tk.Frame(shell, bg=bubble_bg)
        link_row.pack(fill="x", padx=12, pady=(0, 4))

        tk.Label(
            link_row, text=f"📄 {label} generated: ",
            bg=bubble_bg, fg=body_fg,
            font=("TkDefaultFont", sz),
        ).pack(side="left")

        # Clickable filename label
        file_lbl = tk.Label(
            link_row,
            text=Path(output_path).name,
            bg=bubble_bg, fg=c.get("link_fg", "#1b3167"),
            font=("TkDefaultFont", sz, "underline"),
            cursor="hand2",
        )
        file_lbl.pack(side="left")
        file_lbl.bind("<Button-1>", lambda _e, p=output_path: _open_file_in_os(p))

        tk.Label(link_row, text="  ", bg=bubble_bg).pack(side="left")

        # Clickable open-folder label
        folder_lbl = tk.Label(
            link_row,
            text="[Open folder]",
            bg=bubble_bg, fg=c.get("link_folder_fg", "#6b7280"),
            font=("TkDefaultFont", sz, "underline"),
            cursor="hand2",
        )
        folder_lbl.pack(side="left")
        folder_lbl.bind(
            "<Button-1>",
            lambda _e, p=output_path: _open_folder_in_os(str(Path(p).parent)),
        )

        # Propagate scroll from link row widgets
        for w in list(link_row.winfo_children()) + [link_row]:
            self._bind_chat_scroll(w)

        # ── Optional extra-format export (background thread) ─────────────
        if export_fmt != ExportFormat.markdown.value and output_path.endswith(".md"):
            placeholder_lbl = tk.Label(
                shell,
                text=f"⏳ Exporting {export_fmt.upper()}…",
                bg=bubble_bg, fg=c.get("status_fg", "#6b7280"),
                font=("TkDefaultFont", max(sz - 1, 10), "italic"),
                anchor="w", padx=12, pady=4,
            )
            placeholder_lbl.pack(fill="x")
            self._bind_chat_scroll(placeholder_lbl)

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
                        pass
                except Exception as exc:  # noqa: BLE001
                    try:
                        self.after(0, lambda e=str(exc): _finish_export(None, e))
                    except tk.TclError:
                        pass

            def _finish_export(extra_path: str | None, error: str | None) -> None:
                try:
                    if not placeholder_lbl.winfo_exists():
                        return
                    if extra_path:
                        placeholder_lbl.configure(
                            text=f"📥 {export_fmt.upper()} export: {Path(extra_path).name}",
                            fg=c.get("link_fg", "#1565c0"),
                            font=("TkDefaultFont", sz, "underline"),
                            cursor="hand2",
                        )
                        placeholder_lbl.bind(
                            "<Button-1>",
                            lambda _e, p=extra_path: _open_file_in_os(p),
                        )
                    else:
                        placeholder_lbl.configure(
                            text=f"⚠️ Export failed: {error}",
                            fg=c.get("status_fg", "#6b7280"),
                        )
                    self._scroll_chat_to_bottom()
                except tk.TclError:
                    pass

            threading.Thread(target=_export_worker, daemon=True).start()

        self._scroll_chat_to_bottom()

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
        ok = save_session(self._session, ui_extras)
        if not ok:
            self._append_chat(
                "system",
                "⚠️ Session could not be saved — changes may be lost on next launch. "
                "Check available disk space and folder permissions.",
            )


    def _on_cancel(self) -> None:
        """Signal the in-flight background request to be discarded.

        Only sets the cancel event here.  _set_busy(False) is NOT called
        immediately because the background thread may still be running — calling
        _set_busy(False) now would allow a new message to be sent while the old
        thread is still active (race condition).  Instead, each _work() function
        detects the cancel event after its main operation and posts
        _set_busy(False) via after() so the UI is only unlocked once the thread
        has actually finished.
        """
        self._cancel_event.set()
        self._append_chat("system", self._t("request_cancelled"))
