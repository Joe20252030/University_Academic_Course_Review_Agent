"""UACRAgent conversational desktop GUI — pure tkinter, cross-platform.

Layout
------
PanedWindow (horizontal)
├── Session List pane  (~220 px)  — lists all sessions, new / delete
└── Chat pane          (expands)  — chat history + input + quick actions
    └── top bar: [course label]  [⚙ Settings]

Settings are in a separate Toplevel dialog (open/close independently).

Launch:
    python -m uacragent.ui.desktop.app
or:
    from uacragent.ui.desktop.app import main; main()

Architecture
------------
The ``ConversationApp`` class is assembled from four thin mixin modules so
that each concern lives in its own file:

    _ui_constants.py    — string tables, colour palettes, OS helpers
    _appearance_mixin.py — theme / language / App Settings dialog
    _settings_mixin.py  — Session Settings dialog (all 25+ methods)
    _session_mixin.py   — session list panel (refresh, select, new, delete)
    _chat_mixin.py      — chat send/receive and document-indexing

All mixin methods access shared state through ``self`` — the instance
variables are initialised once in ``ConversationApp.__init__`` and
``_init_setting_vars``.
"""
from __future__ import annotations

import os
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from uacragent.agent.conversation import ConversationAgent, ChatResponse
from uacragent.agent.session import AgentSession
from uacragent.domain.errors import UACRAgentError
from uacragent.domain.types import DocumentType, ExamFormat, ExamType, ExportFormat
from uacragent.export.docx import save_docx
from uacragent.export.pdf import save_pdf
from uacragent.infra.persistence import (
    delete_session, dict_to_session, get_app_appearance, get_app_data_dir,
    get_missing_session_files, list_sessions, load_session, rename_session,
    save_session, set_app_appearance, set_app_data_dir,
)
from uacragent.infra.workspace import workspace_paths, ensure_workspace_dirs

# Re-export module-level constants and helpers so existing callers that
# ``from uacragent.ui.desktop.app import _strip_markdown`` still work.
from ._ui_constants import (  # noqa: F401 (re-exports)
    _WINDOW_TITLE, _MIN_WIDTH, _MIN_HEIGHT, _PAD, _SESSION_LIST_WIDTH,
    _SUPPORTED_FILETYPES, _DOC_TYPE_LABELS, _QUICK_ACTIONS,
    _STRINGS, _THEME_COLORS, _FONT_SIZE_VALUES,
    _open_in_os, _open_file_in_os, _open_folder_in_os,
    _strip_markdown, _fmt_dt,
)
from ._appearance_mixin import AppearanceMixin
from ._settings_mixin import SettingsMixin
from ._session_mixin import SessionMixin
from ._chat_mixin import ChatMixin


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class ConversationApp(AppearanceMixin, SettingsMixin, SessionMixin, ChatMixin, tk.Tk):
    """Three-panel app: session list | chat area.

    Settings live in a separate Toplevel dialog.  All domain logic is
    delegated to the mixin classes listed above; this class is responsible
    only for construction, shared state initialisation, and lifecycle hooks.
    """

    def __init__(self) -> None:
        super().__init__()
        self.title(_WINDOW_TITLE)
        self.minsize(_MIN_WIDTH, _MIN_HEIGHT)

        # ── App icon ─────────────────────────────────────────────────────────
        # Look for the icon relative to this file so it works whether the app
        # is run from source or installed as a package.
        _assets = Path(__file__).parent.parent.parent.parent.parent / "assets"
        try:
            from PIL.ImageTk import PhotoImage as _PILPhotoImage
            _icon_path = _assets / "logo_256.png"
            if _icon_path.exists():
                _icon_img = _PILPhotoImage(file=str(_icon_path))
                self.iconphoto(True, _icon_img)
                # Keep a reference so it isn't garbage-collected
                self._app_icon = _icon_img
        except Exception:  # noqa: BLE001
            pass  # icon is cosmetic — never crash on failure

        # Centre the main window on the primary display before showing it.
        # withdraw() hides it so the user never sees it in the wrong position.
        self.withdraw()
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - _MIN_WIDTH)  // 2
        y = (sh - _MIN_HEIGHT) // 2
        self.geometry(f"{_MIN_WIDTH}x{_MIN_HEIGHT}+{x}+{y}")
        self.deiconify()

        # Active session
        self._session = AgentSession()
        self._agent: ConversationAgent | None = None
        self._is_busy = False
        self._cancel_event = threading.Event()  # set to abort in-flight requests

        # True once a session's workspace has been committed (Apply was clicked
        # with a course name, or a saved session was loaded). Prevents the
        # workspace from being changed.
        self._workspace_committed = False

        # Set to True while _refresh_session_list runs so that the programmatic
        # lb.selection_set() inside it does not re-trigger _on_session_select.
        self._updating_session_list = False

        # Staging area for file-list edits made inside the settings dialog.
        # Changes here are NOT written to session.classified_files until the
        # user clicks Apply.  Closing the dialog without Apply discards them.
        self._staged_files: dict[DocumentType, list[str]] = {}

        # Settings Toplevel (created lazily, kept alive while open)
        self._settings_win: tk.Toplevel | None = None

        # File listboxes live inside the settings dialog
        self._file_listboxes: dict[DocumentType, tk.Listbox] = {}

        # StringVars for all settings fields (created here so they work
        # even before the settings dialog is first opened)
        self._init_setting_vars()

        # Save the platform's native ttk theme so we can restore it for light mode.
        self._default_ttk_theme: str = ttk.Style(self).theme_use()

        # Load persisted appearance BEFORE building UI so _t() uses the right
        # language and theme vars are set when widgets are first created.
        self._load_app_appearance()

        self._build_ui()

        # Apply visual theme and font size now that all widgets exist.
        # Pass reconfigure_tags=False to _apply_theme so that chat tags are
        # only configured once — by the _apply_font_size() call that follows.
        self._apply_theme(reconfigure_tags=False)
        self._apply_font_size()

        # Populate the session list but do not auto-select anything.
        # The right panel stays blank until the user clicks a session.
        self._refresh_session_list()
        self._show_idle()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # StringVar initialisation (settings fields)
    # ------------------------------------------------------------------

    def _init_setting_vars(self) -> None:
        # Global app data dir (shown/edited in the App Settings dialog)
        self._app_data_dir_var = tk.StringVar(value=str(get_app_data_dir()))

        # Per-provider API key vars (pre-populate from env)
        self._gemini_key_var   = tk.StringVar(
            value=os.environ.get("GOOGLE_API_KEY", "").strip())
        self._openai_key_var   = tk.StringVar(
            value=os.environ.get("OPENAI_API_KEY", "").strip())
        self._deepseek_key_var = tk.StringVar(
            value=os.environ.get("DEEPSEEK_API_KEY", "").strip())

        # Model selection
        self._llm_provider_var      = tk.StringVar(value="gemini")
        self._llm_model_var         = tk.StringVar(value="gemini-2.5-flash")

        # Embedding: internal key ("gemini"/"openai"/"local") + its display string
        self._emb_provider_var      = tk.StringVar(value="gemini")
        self._emb_provider_disp_var = tk.StringVar(
            value=self._EMB_PROVIDER_DISPLAY.get("gemini", ""))
        # Free local model: internal name + display string
        _default_local = "all-MiniLM-L6-v2"
        self._local_model_var       = tk.StringVar(value=_default_local)
        self._local_model_disp_var  = tk.StringVar(
            value=self._FREE_EMB_MODEL_TO_DISPLAY.get(_default_local, _default_local))

        self._course_name_var  = tk.StringVar()
        self._university_var   = tk.StringVar()
        self._major_var        = tk.StringVar()
        self._course_code_var  = tk.StringVar()
        self._professor_var    = tk.StringVar()
        self._semester_var     = tk.StringVar()

        self._exam_type_var    = tk.StringVar(value=ExamType.final.value)
        self._exam_format_var  = tk.StringVar(value=ExamFormat.written.value)
        self._exam_duration_var = tk.StringVar()
        self._exam_info_path_var = tk.StringVar()

        self._workspace_var    = tk.StringVar()
        self._export_format_var = tk.StringVar(value=ExportFormat.markdown.value)
        self._extra_instructions_var = tk.StringVar()

        # Effort level for each chat turn (Low / Medium / High).
        # Use .set() instead of replacing the var after the first init so that
        # the radio buttons (built once in _build_chat_pane) keep their binding.
        if hasattr(self, "_effort_var"):
            self._effort_var.set("medium")
        else:
            self._effort_var = tk.StringVar(value="medium")

        # ── Appearance vars (created once; never reset by _on_new_session) ──
        # Use hasattr so _on_new_session calling this method doesn't clobber them.
        if not hasattr(self, "_color_mode_var"):
            self._color_mode_var = tk.StringVar(value="light")
        if not hasattr(self, "_font_size_var"):
            self._font_size_var = tk.StringVar(value="medium")
        if not hasattr(self, "_language_var"):
            self._language_var = tk.StringVar(value="en")
        # Rate-tier var: global, survives session switches.
        # Initialise from RATE_TIER env var so a .env override is honoured on
        # startup; fall back to "Free" (the safe default) when absent.
        if not hasattr(self, "_rate_tier_disp_var"):
            from uacragent.domain.rate_tiers import RATE_TIERS, get_rate_tier
            _tier_id = os.environ.get("RATE_TIER", "free")
            _tier_cfg = get_rate_tier(_tier_id)
            self._rate_tier_disp_var = tk.StringVar(value=_tier_cfg.display_name)
        # i18n widget registry: list of (widget, config_attr, string_key)
        if not hasattr(self, "_i18n_widgets"):
            self._i18n_widgets: list[tuple] = []

    # ------------------------------------------------------------------
    # UI layout
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        paned = tk.PanedWindow(self, orient="horizontal",
                               sashwidth=5, sashrelief="flat",
                               background="#cccccc")
        paned.grid(row=0, column=0, sticky="nsew")
        self._paned = paned

        self._build_session_list_pane()
        self._build_chat_pane()

    # ── Session list pane ─────────────────────────────────────────────

    def _build_session_list_pane(self) -> None:
        frame = ttk.Frame(self._paned, width=_SESSION_LIST_WIDTH)
        frame.grid_propagate(False)
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)
        self._paned.add(frame, minsize=160, stretch="never")

        # Header
        hdr = ttk.Frame(frame, padding=(6, 6, 6, 4))
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.columnconfigure(0, weight=1)

        _lbl = ttk.Label(hdr, text=self._t("sessions"), font=("TkDefaultFont", 11, "bold"))
        _lbl.grid(row=0, column=0, sticky="w")
        self._i18n_widgets.append((_lbl, "text", "sessions"))

        _btn_new = ttk.Button(hdr, text=self._t("new_session"), width=7,
                              command=self._on_new_session)
        _btn_new.grid(row=0, column=1, padx=(0, 3))
        self._i18n_widgets.append((_btn_new, "text", "new_session"))

        self._gear_btn = ttk.Button(hdr, text="⚙", width=3,
                                    style="Gear.TButton",
                                    command=self._open_app_settings)
        self._gear_btn.grid(row=0, column=2)

        ttk.Separator(frame, orient="horizontal").grid(
            row=0, column=0, sticky="ew", pady=(36, 0)
        )

        # Session listbox
        list_frame = ttk.Frame(frame)
        list_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        self._session_listbox = tk.Listbox(
            list_frame, selectmode=tk.SINGLE,
            font=("TkDefaultFont", 10),
            activestyle="none",
            relief="flat", borderwidth=0,
            highlightthickness=0,
        )
        sb = ttk.Scrollbar(list_frame, orient="vertical",
                           command=self._session_listbox.yview)
        self._session_listbox.configure(yscrollcommand=sb.set)
        self._session_listbox.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self._session_listbox.bind("<<ListboxSelect>>", self._on_session_select)
        self._session_listbox.bind("<Double-Button-1>", self._on_rename_session)

        # Rename / Delete buttons at the bottom
        ttk.Separator(frame, orient="horizontal").grid(
            row=2, column=0, sticky="ew"
        )
        action_btns = ttk.Frame(frame)
        action_btns.grid(row=3, column=0, sticky="ew", padx=6, pady=6)
        action_btns.columnconfigure(0, weight=1)
        action_btns.columnconfigure(1, weight=1)

        _btn_rename = ttk.Button(action_btns, text=self._t("rename"),
                                 command=self._on_rename_session)
        _btn_rename.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self._i18n_widgets.append((_btn_rename, "text", "rename"))

        _btn_delete = ttk.Button(action_btns, text=self._t("delete"),
                                 command=self._on_delete_session)
        _btn_delete.grid(row=0, column=1, sticky="ew")
        self._i18n_widgets.append((_btn_delete, "text", "delete"))

        # Keep the workspace list in sync with what we display
        self._session_records: list[dict] = []   # parallel to listbox entries

    # ── Chat pane ─────────────────────────────────────────────────────

    def _build_chat_pane(self) -> None:
        right = ttk.Frame(self._paned, padding=_PAD)
        right.rowconfigure(1, weight=1)
        right.rowconfigure(2, weight=0)
        right.rowconfigure(3, weight=0)
        right.columnconfigure(0, weight=1)
        self._paned.add(right, minsize=500, stretch="always")

        # ── Top bar ───────────────────────────────────────────────────
        self._chat_top_bar = top_bar = ttk.Frame(right)
        top_bar.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        top_bar.columnconfigure(0, weight=1)

        self._header_course_var = tk.StringVar(value=self._t("no_session_loaded"))
        ttk.Label(
            top_bar, textvariable=self._header_course_var,
            font=("TkDefaultFont", 12, "bold"),
        ).grid(row=0, column=0, sticky="w")

        self._session_status_var = tk.StringVar(value="")
        self._session_status_lbl = ttk.Label(
            top_bar, textvariable=self._session_status_var,
            foreground="gray", font=("TkDefaultFont", 10),
        )
        self._session_status_lbl.grid(row=1, column=0, sticky="w")

        btn_frame = ttk.Frame(top_bar)
        btn_frame.grid(row=0, column=1, rowspan=2, sticky="e")

        _btn_sess_settings = ttk.Button(
            btn_frame, text=self._t("settings_btn"), command=self._open_settings
        )
        _btn_sess_settings.pack(side="left")
        self._i18n_widgets.append((_btn_sess_settings, "text", "settings_btn"))

        self._chat_separator = ttk.Separator(right, orient="horizontal")
        self._chat_separator.grid(row=0, column=0, sticky="ew", pady=(42, 0))

        # ── Chat history ──────────────────────────────────────────────
        self._hist_frame = hist_frame = ttk.Frame(right)
        hist_frame.grid(row=1, column=0, sticky="nsew")
        hist_frame.rowconfigure(0, weight=1)
        hist_frame.columnconfigure(0, weight=1)

        self._chat_text = tk.Text(
            hist_frame, wrap="word", state="disabled",
            font=("TkDefaultFont", 11), padx=8, pady=8,
        )
        chat_sb = ttk.Scrollbar(hist_frame, orient="vertical",
                                command=self._chat_text.yview)
        self._chat_text.configure(yscrollcommand=chat_sb.set)
        self._chat_text.grid(row=0, column=0, sticky="nsew")
        chat_sb.grid(row=0, column=1, sticky="ns")

        # Tag colours are set by _reconfigure_chat_tags(); defaults below
        # match the light theme and will be overridden on startup if dark mode
        # is loaded from config.
        self._chat_text.tag_configure(
            "user_label", font=("TkDefaultFont", 10, "bold"),
            foreground="#1a56a5", spacing1=10)
        self._chat_text.tag_configure(
            "user_body", foreground="#1a56a5", lmargin1=8, lmargin2=8)
        self._chat_text.tag_configure(
            "assistant_label", font=("TkDefaultFont", 10, "bold"),
            foreground="#2e7d32", spacing1=10)
        self._chat_text.tag_configure(
            "assistant_body", foreground="#1a1a1a", lmargin1=8, lmargin2=8)
        self._chat_text.tag_configure(
            "system_body", foreground="#7b5800", lmargin1=8, lmargin2=8,
            font=("TkDefaultFont", 10, "italic"), spacing1=6)

        # ── Quick actions ─────────────────────────────────────────────
        self._qa_frame = qa_frame = ttk.LabelFrame(
            right, text=self._t("quick_actions"), padding=4)
        qa_frame.grid(row=2, column=0, sticky="ew", pady=(_PAD, 4))
        self._i18n_widgets.append((qa_frame, "text", "quick_actions"))
        for _qa_key, _qa_msg in _QUICK_ACTIONS:
            _qa_btn = ttk.Button(qa_frame, text=self._t(_qa_key),
                                 command=lambda m=_qa_msg: self._send_message(m))
            _qa_btn.pack(side="left", padx=3, pady=2)
            self._i18n_widgets.append((_qa_btn, "text", _qa_key))

        # ── Input area ────────────────────────────────────────────────
        self._input_frame = input_frame = ttk.Frame(right)
        input_frame.grid(row=3, column=0, sticky="ew")
        input_frame.columnconfigure(0, weight=1)

        self._input_text = tk.Text(
            input_frame, height=3, wrap="word",
            font=("TkDefaultFont", 11),
        )
        self._input_text.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self._input_text.bind("<Return>", self._on_return_key)

        # ── Effort level selector (Low / Medium / High) ───────────────
        effort_row = ttk.Frame(input_frame)
        effort_row.grid(row=1, column=0, sticky="w", pady=(3, 0))
        _effort_lbl = ttk.Label(effort_row, text=self._t("effort_label"), foreground="gray")
        _effort_lbl.pack(side="left", padx=(2, 4))
        self._i18n_widgets.append((_effort_lbl, "text", "effort_label"))
        for _level, _key in [("low", "low"), ("medium", "medium"), ("high", "high")]:
            _rb = ttk.Radiobutton(effort_row, text=self._t(_key),
                                  value=_level, variable=self._effort_var)
            _rb.pack(side="left", padx=(0, 6))
            self._i18n_widgets.append((_rb, "text", _key))

        btn_col = ttk.Frame(input_frame)
        btn_col.grid(row=0, column=1, sticky="ns")
        self._send_btn = ttk.Button(btn_col, text=self._t("send"), width=8,
                                    command=self._on_send)
        self._send_btn.pack(fill="x", pady=(0, 4))
        self._i18n_widgets.append((self._send_btn, "text", "send"))
        self._cancel_btn = ttk.Button(btn_col, text=self._t("cancel"), width=8,
                                      command=self._on_cancel)
        self._i18n_widgets.append((self._cancel_btn, "text", "cancel"))
        # _cancel_btn is pack()ed / pack_forget()en dynamically by _set_busy
        self._busy_label = ttk.Label(btn_col, text="", foreground="gray",
                                     font=("TkDefaultFont", 10), wraplength=72)
        self._busy_label.pack()

        # ── Placeholder (shown when no session is active) ─────────────
        self._placeholder_frame = ttk.Frame(right)
        _ph_lbl = ttk.Label(
            self._placeholder_frame,
            text=self._t("placeholder"),
            foreground="#aaaaaa",
            font=("TkDefaultFont", 14),
            justify="center",
        )
        _ph_lbl.place(relx=0.5, rely=0.5, anchor="center")
        self._i18n_widgets.append((_ph_lbl, "text", "placeholder"))

        # Start in blank state — activated by session select or + New.
        self._set_chat_active(False)

    # ------------------------------------------------------------------
    # Chat pane show / hide
    # ------------------------------------------------------------------

    def _set_chat_active(self, active: bool) -> None:
        """Show the full chat UI (active=True) or a blank placeholder (active=False)."""
        chat_widgets = [
            self._chat_top_bar,
            self._chat_separator,
            self._hist_frame,
            self._qa_frame,
            self._input_frame,
        ]
        if active:
            self._placeholder_frame.grid_remove()
            for w in chat_widgets:
                w.grid()          # restores original grid options saved by grid_remove()
        else:
            for w in chat_widgets:
                w.grid_remove()
            self._placeholder_frame.grid(
                row=0, column=0, rowspan=4, sticky="nsew")

    # ------------------------------------------------------------------
    # Window lifecycle
    # ------------------------------------------------------------------

    def _on_close(self) -> None:
        self._save_current_session()

        # Erase API keys from in-process memory before the window is destroyed.
        # The process exit would clean these up anyway, but explicit zeroing is
        # the correct security practice — it removes key material immediately
        # rather than leaving it in the process heap until the OS reclaims it.
        for var in (self._gemini_key_var, self._openai_key_var, self._deepseek_key_var):
            try:
                var.set("")
            except Exception:  # noqa: BLE001
                pass
        for env_var in (
            "GOOGLE_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY",
            "EMBEDDING_PROVIDER", "LOCAL_EMBEDDING_MODEL",
        ):
            os.environ.pop(env_var, None)

        self.destroy()

    # ------------------------------------------------------------------
    # Busy state
    # ------------------------------------------------------------------

    def _set_busy(self, busy: bool, label: str = "") -> None:
        self._is_busy = busy
        self._send_btn.configure(state="disabled" if busy else "normal")
        self._busy_label.configure(text=label)
        if busy:
            self._cancel_event.clear()
            self._cancel_btn.pack(fill="x", pady=(2, 0))
        else:
            self._cancel_btn.pack_forget()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()
    # Redirect HuggingFace model downloads into the app data folder so all
    # agent data lives in one place.  Must run before any HF import.
    from uacragent.infra.persistence import configure_hf_cache
    configure_hf_cache()

    # Remove the legacy last_session.json written by older app versions.
    # It is no longer used and its presence is misleading.  It never contained
    # API keys (confirmed), but deleting it keeps the data directory clean and
    # removes any ambiguity for future security audits.
    _legacy = Path.home() / ".uacragent" / "last_session.json"
    try:
        _legacy.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass  # non-fatal; stale file remains but causes no harm

    app = ConversationApp()
    app.mainloop()


if __name__ == "__main__":
    main()
