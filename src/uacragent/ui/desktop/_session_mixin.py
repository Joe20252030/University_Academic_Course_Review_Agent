"""Session list management methods."""
from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from uacragent.agent.session import AgentSession
from uacragent.domain.types import ExportFormat
from uacragent.infra.persistence import (
    delete_session, dict_to_session, get_app_data_dir,
    get_missing_session_files, list_sessions, load_session,
    rename_session, save_session,
)
from uacragent.infra.workspace import workspace_paths

from ._ui_constants import _fmt_dt


class SessionMixin:
    """Mixin: session-list panel — refresh, select, new, delete, rename, load."""
    def _refresh_session_list(self) -> None:
        self._session_records = list_sessions()
        # Apply search filter so the list stays consistent with the query.
        query = getattr(self, "_search_var", None)
        query = query.get().strip().lower() if query else ""
        if query:
            visible = [r for r in self._session_records
                       if query in (r.get("course_name") or "").lower()]
        else:
            visible = self._session_records
        # Track which records are currently shown so _on_session_select,
        # _on_rename_session, and _on_delete_session index into the right list.
        self._visible_records = visible
        active_ws = self._session.workspace_folder if self._workspace_committed else None
        self._session_list.refresh(visible, active_ws)

    def _on_search_changed(self) -> None:
        """Re-filter the visible session list whenever the search query changes.

        Filters the in-memory ``_session_records`` list without hitting disk
        again — fast enough for real-time keystroke filtering.
        """
        if not hasattr(self, "_session_records") or not hasattr(self, "_session_list"):
            return
        query = getattr(self, "_search_var", None)
        query = query.get().strip().lower() if query else ""
        if query:
            visible = [r for r in self._session_records
                       if query in (r.get("course_name") or "").lower()]
        else:
            visible = self._session_records
        self._visible_records = visible
        active_ws = self._session.workspace_folder if self._workspace_committed else None
        self._session_list.refresh(visible, active_ws)

    def _on_session_select(self, idx: int = None) -> None:
        if idx is None:
            sel = self._session_list.curselection()
            if not sel:
                return
            idx = sel[0]
        visible = getattr(self, "_visible_records", self._session_records)
        if idx >= len(visible):
            return
        ws = Path(visible[idx]["workspace"])
        # Return keyboard focus to the main window so the search entry
        # stops capturing keystrokes after a session is selected.
        try:
            self.focus_set()
        except Exception:
            pass
        self._set_chat_active(True)
        # Load metadata + replay history immediately, then attach retriever.
        self._load_session_from_workspace(ws)
        self._attach_session_async()

    def _on_new_session(self) -> None:
        """Start a blank session and open settings so the user can fill it in."""
        # Inherit the active LLM provider/model so the user doesn't have to
        # re-enter them for every new session.  API keys are already in os.environ.
        prev_provider = self._llm_provider_var.get() or "gemini"
        prev_model    = self._llm_model_var.get() or "gemini-2.5-flash"
        self._session = AgentSession(llm_provider=prev_provider, llm_model=prev_model)
        self._workspace_committed = False  # new session: workspace not yet locked
        self._file_listboxes = {}          # clear stale widget refs
        self._init_setting_vars()          # reset all vars (creates fresh StringVars)
        self._sync_vars_from_session()     # pushes inherited provider/model into vars
        self._set_chat_active(True)
        self._header_course_var.set(self._t("new_session_header"))
        self._session_status_var.set("")
        self._clear_chat()
        self._show_welcome()
        # Hint shown as a system message in chat so the title row stays clean.
        self._append_chat("system", self._t("new_session_hint"))
        self._open_settings()

    def _on_delete_session(self, idx: int = None) -> None:
        if idx is None:
            idx = self._session_list.get_selected_idx()
        if idx is None:
            self._show_info_dialog(
                self._t("mb_delete_session_title"),
                self._t("mb_delete_session_select"))
            return
        visible = getattr(self, "_visible_records", self._session_records)
        if idx >= len(visible):
            return
        rec = visible[idx]
        name = rec.get("course_name") or Path(rec["workspace"]).name
        if not self._show_confirm_dialog(
            self._t("mb_delete_session_title"),
            self._t("mb_delete_session_confirm").format(name=name),
            confirm_text=self._t("delete"),
            destructive=True,
        ):
            return
        ws = Path(rec["workspace"])
        delete_session(ws)
        # If the deleted session is the active one, return to a clean idle state.
        # _workspace_committed MUST be reset here — without it, _on_close() would
        # call _save_current_session() on the blank AgentSession(), creating a
        # phantom entry in the index that re-appears on the next launch.
        #
        # Compute the effective workspace for the currently active session:
        # prefer the explicit workspace_folder; fall back to the auto-path derived
        # from workspace_id (for UUID-based sessions whose folder was never set
        # by the user but was committed via Apply or session load).
        if self._session.workspace_folder:
            active_ws: Path | None = Path(self._session.workspace_folder).resolve()
        elif self._session.workspace_id:
            active_ws = (
                get_app_data_dir() / "sessions" / self._session.workspace_id
            ).resolve()
        else:
            active_ws = None
        if active_ws is not None and active_ws == ws.resolve():
            self._session = AgentSession()
            self._workspace_committed = False
            self._show_idle()
        self._refresh_session_list()

    def _on_rename_session(self, idx: int = None, _event: object = None) -> None:
        if idx is None:
            idx = self._session_list.get_selected_idx()
        if idx is None:
            self._show_info_dialog(
                self._t("mb_rename_session_title"),
                self._t("mb_rename_session_select"))
            return
        visible = getattr(self, "_visible_records", self._session_records)
        if idx >= len(visible):
            return
        rec = visible[idx]
        current_name = (rec.get("display_name")
                        or rec.get("course_name")
                        or Path(rec["workspace"]).name)
        new_name = self._show_rename_dialog(
            self._t("mb_rename_session_title"),
            self._t("mb_rename_session_prompt"),
            initial=current_name,
        )
        if new_name is None or not new_name.strip():
            return
        ws = Path(rec["workspace"])
        rename_session(ws, new_name.strip())
        # _refresh_session_list() re-selects the active session automatically.
        self._refresh_session_list()

    def _load_session_from_workspace(self, ws: Path) -> None:
        # Clear any leftover status from the previous session (e.g. "Fill in
        # the settings and click Apply." left by an abandoned new-session flow).
        self._session_status_var.set("")
        data = load_session(ws)
        if data is None:
            self._append_chat(
                "system",
                self._t("warn_load_fail").format(ws=ws),
            )
            return
        self._session = dict_to_session(data)
        # Sessions loaded from disk already have a committed workspace.
        self._workspace_committed = True

        # Warn if any previously-indexed files are no longer on disk.
        _missing = get_missing_session_files(data)
        if _missing:
            _names = "\n  • ".join(Path(p).name for p in _missing)
            self._append_chat(
                "system",
                self._t("warn_missing_files").format(n=len(_missing), names=_names),
            )

        # Restore UI extras (stored alongside session data in session.json)
        export_fmt   = data.get("export_format", ExportFormat.markdown.value)
        emb_provider = data.get("embedding_provider", "gemini")
        local_model  = data.get("local_embedding_model", "all-MiniLM-L6-v2")
        self._export_format_var.set(export_fmt)
        self._emb_provider_var.set(emb_provider)
        self._emb_provider_disp_var.set(
            self._EMB_PROVIDER_DISPLAY.get(emb_provider, emb_provider))
        self._local_model_var.set(local_model)
        self._local_model_disp_var.set(
            self._FREE_EMB_MODEL_TO_DISPLAY.get(local_model, local_model))

        # Commit the embedding provider into os.environ immediately so that
        # auto-indexing on session load uses the correct provider.
        # Without this, Settings() would fall back to whatever EMBEDDING_PROVIDER
        # was set previously (or default "gemini"), ignoring the saved value.
        os.environ["EMBEDDING_PROVIDER"] = emb_provider
        if emb_provider == "local":
            os.environ["LOCAL_EMBEDDING_MODEL"] = local_model

        self._sync_vars_from_session()
        self._update_header()
        self._clear_chat()
        self._replay_chat_history()
        # _refresh_session_list() automatically re-selects the active session
        # (matched by workspace_folder), so no manual re-selection needed here.
        self._refresh_session_list()

    # ------------------------------------------------------------------
    # Indexing  (shared core used by sidebar select and Apply)
