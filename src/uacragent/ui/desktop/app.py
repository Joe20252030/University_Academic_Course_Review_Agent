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
"""
from __future__ import annotations

import os
import platform
import subprocess
import threading
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Optional

from uacragent.agent.conversation import ConversationAgent, ChatResponse
from uacragent.agent.session import AgentSession
from uacragent.domain.errors import UACRAgentError
from uacragent.domain.types import DocumentType, ExamFormat, ExamType, ExportFormat
from uacragent.export.docx import save_docx
from uacragent.export.pdf import save_pdf
from uacragent.infra.persistence import (
    delete_session, dict_to_session, get_app_data_dir, list_sessions,
    load_session, rename_session, save_session, set_app_data_dir,
)
from uacragent.infra.workspace import workspace_paths, ensure_workspace_dirs


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_WINDOW_TITLE = "UACRAgent - Course Review Assistant"
_MIN_WIDTH = 1000
_MIN_HEIGHT = 620
_PAD = 8
_SESSION_LIST_WIDTH = 220

_SUPPORTED_FILETYPES = [
    ("All supported", "*.pdf *.txt *.md *.docx"),
    ("PDF files", "*.pdf"),
    ("Word documents", "*.docx"),
    ("Text files", "*.txt"),
    ("Markdown files", "*.md"),
]
_DOC_TYPE_LABELS = {
    DocumentType.syllabus: "Syllabus",
    DocumentType.lecture_note: "Lecture Notes",
    DocumentType.textbook: "Textbook",
    DocumentType.assignment: "Assignments",
    DocumentType.past_exam: "Past Exams",
    DocumentType.other: "Other",
}
_QUICK_ACTIONS = [
    ("Review Summary",   "Generate a review summary for this course."),
    ("Practice Booklet", "Generate a practice booklet for this course."),
    ("Mock Exam",        "Generate a mock exam for this course."),
    ("Exam Prediction",  "Generate an exam prediction for this course."),
]


# ---------------------------------------------------------------------------
# OS helpers
# ---------------------------------------------------------------------------
def _open_file_in_os(path: str) -> None:
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.Popen(["open", path])
        elif system == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


def _open_folder_in_os(path: str) -> None:
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.Popen(["open", path])
        elif system == "Windows":
            subprocess.Popen(["explorer", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


def _fmt_dt(iso: str) -> str:
    """Format an ISO timestamp for display in the session list."""
    try:
        dt = datetime.fromisoformat(iso).astimezone()
        return dt.strftime("%b %d, %Y")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class ConversationApp(tk.Tk):
    """Three-panel app: session list | chat area.
    Settings live in a separate Toplevel dialog.
    """

    def __init__(self) -> None:
        super().__init__()
        self.title(_WINDOW_TITLE)
        self.minsize(_MIN_WIDTH, _MIN_HEIGHT)

        # Active session
        self._session = AgentSession()
        self._agent: Optional[ConversationAgent] = None
        self._is_busy = False
        self._cancel_event = threading.Event()  # set to abort in-flight requests

        # True once a session's workspace has been committed (Apply was clicked
        # with a course name, or a saved session was loaded). Prevents the
        # workspace from being changed.
        self._workspace_committed = False

        # Settings Toplevel (created lazily, kept alive while open)
        self._settings_win: Optional[tk.Toplevel] = None

        # File listboxes live inside the settings dialog
        self._file_listboxes: dict[DocumentType, tk.Listbox] = {}

        # StringVars for all settings fields (created here so they work
        # even before the settings dialog is first opened)
        self._init_setting_vars()

        self._build_ui()

        # Populate the session list but do not auto-select anything.
        # The right panel stays blank until the user clicks a session.
        self._refresh_session_list()
        self._show_idle()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # StringVar initialisation (settings fields)
    # ------------------------------------------------------------------

    # Provider → available models
    _PROVIDER_MODELS: dict[str, list[str]] = {
        "gemini":   ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash",
                     "gemini-1.5-pro", "gemini-1.5-flash"],
        "openai":   ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
        "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    }
    # ── Embedding provider choices ────────────────────────────────────────
    # Display label → internal key used in Settings / env vars
    _EMB_PROVIDER_OPTIONS: dict[str, str] = {
        "Gemini  (Google API key)":          "gemini",
        "OpenAI  (OpenAI API key)":          "openai",
        "★ Free — Local  (no key needed)":   "local",
    }
    # Internal key → display label (reverse map)
    _EMB_PROVIDER_DISPLAY: dict[str, str] = {
        v: k for k, v in _EMB_PROVIDER_OPTIONS.items()
    }

    # Free local models:  display label → HuggingFace model name
    _FREE_EMB_MODELS: dict[str, str] = {
        "all-MiniLM-L6-v2  ★ recommended  (~80 MB)":            "all-MiniLM-L6-v2",
        "all-MiniLM-L12-v2  (balanced, ~120 MB)":              "all-MiniLM-L12-v2",
        "all-mpnet-base-v2  (high quality, ~420 MB)":          "all-mpnet-base-v2",
        "BAAI/bge-small-en-v1.5  (fast, ~130 MB)":             "BAAI/bge-small-en-v1.5",
        "BAAI/bge-base-en-v1.5  (quality, ~440 MB)":           "BAAI/bge-base-en-v1.5",
        "paraphrase-multilingual-MiniLM-L12-v2  (~470 MB)":    "paraphrase-multilingual-MiniLM-L12-v2",
    }
    _FREE_EMB_MODEL_TO_DISPLAY: dict[str, str] = {
        v: k for k, v in _FREE_EMB_MODELS.items()
    }

    # Provider → env-var label shown next to the key field
    _PROVIDER_KEY_LABEL: dict[str, str] = {
        "gemini":   "Google API Key",
        "openai":   "OpenAI API Key",
        "deepseek": "DeepSeek API Key",
    }
    _PROVIDER_KEY_ENV: dict[str, str] = {
        "gemini":   "GOOGLE_API_KEY",
        "openai":   "OPENAI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
    }

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
        ttk.Label(hdr, text="Sessions", font=("TkDefaultFont", 11, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(hdr, text="+ New", width=7, command=self._on_new_session).grid(
            row=0, column=1, padx=(0, 3)
        )
        ttk.Button(hdr, text="⚙", width=3,
                   command=self._open_app_settings).grid(row=0, column=2)

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
        ttk.Button(
            action_btns, text="✏  Rename", command=self._on_rename_session
        ).grid(row=0, column=0, sticky="ew", padx=(0, 3))
        ttk.Button(
            action_btns, text="🗑  Delete", command=self._on_delete_session
        ).grid(row=0, column=1, sticky="ew")

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

        self._header_course_var = tk.StringVar(value="No session loaded")
        ttk.Label(
            top_bar, textvariable=self._header_course_var,
            font=("TkDefaultFont", 12, "bold"),
        ).grid(row=0, column=0, sticky="w")

        self._session_status_var = tk.StringVar(value="")
        ttk.Label(
            top_bar, textvariable=self._session_status_var,
            foreground="gray", font=("TkDefaultFont", 9),
        ).grid(row=1, column=0, sticky="w")

        btn_frame = ttk.Frame(top_bar)
        btn_frame.grid(row=0, column=1, rowspan=2, sticky="e")

        self._load_btn = ttk.Button(
            btn_frame, text="⟳  Re-index", command=self._on_load_session
        )
        self._load_btn.pack(side="left", padx=(0, 6))

        ttk.Button(
            btn_frame, text="⚙  Settings", command=self._open_settings
        ).pack(side="left")

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
        self._qa_frame = qa_frame = ttk.LabelFrame(right, text="Quick Actions", padding=4)
        qa_frame.grid(row=2, column=0, sticky="ew", pady=(_PAD, 4))
        for label, message in _QUICK_ACTIONS:
            ttk.Button(qa_frame, text=label,
                       command=lambda m=message: self._send_message(m)
                       ).pack(side="left", padx=3, pady=2)

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

        btn_col = ttk.Frame(input_frame)
        btn_col.grid(row=0, column=1, sticky="ns")
        self._send_btn = ttk.Button(btn_col, text="Send", width=8,
                                    command=self._on_send)
        self._send_btn.pack(fill="x", pady=(0, 4))
        self._cancel_btn = ttk.Button(btn_col, text="✕ Cancel", width=8,
                                      command=self._on_cancel)
        # _cancel_btn is pack()ed / pack_forget()en dynamically by _set_busy
        self._busy_label = ttk.Label(btn_col, text="", foreground="gray",
                                     font=("TkDefaultFont", 9), wraplength=72)
        self._busy_label.pack()

        # ── Placeholder (shown when no session is active) ─────────────
        self._placeholder_frame = ttk.Frame(right)
        ttk.Label(
            self._placeholder_frame,
            text="Select a session from the left panel\nor click  + New  to create a new one.",
            foreground="#aaaaaa",
            font=("TkDefaultFont", 14),
            justify="center",
        ).place(relx=0.5, rely=0.5, anchor="center")

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
    # Settings Toplevel dialog
    # ------------------------------------------------------------------

    def _reset_setting_vars_from_committed(self) -> None:
        """Reset every setting StringVar to the last *committed* state.

        Called each time the Settings dialog is freshly opened so that any
        edits the user made and then discarded (closed without clicking Apply)
        are thrown away rather than shown as if they were the real values.

        Committed sources:
          • API keys  → os.environ  (written by _inject_api_keys via Apply)
          • Everything else → self._session  (written by _sync_session_from_vars via Apply)
        """
        # API keys — ground truth is os.environ, NOT the StringVars
        self._gemini_key_var.set(os.environ.get("GOOGLE_API_KEY", "").strip())
        self._openai_key_var.set(os.environ.get("OPENAI_API_KEY", "").strip())
        self._deepseek_key_var.set(os.environ.get("DEEPSEEK_API_KEY", "").strip())

        # Session fields — ground truth is self._session
        # _sync_vars_from_session() is safe to call before the dialog is built:
        # the file-listbox and _extra_text updates inside it are guarded by
        # _settings_alive() which returns False at this point.
        self._sync_vars_from_session()

    def _open_settings(self) -> None:
        """Open (or bring to front) the settings dialog."""
        if self._settings_win is not None and self._settings_win.winfo_exists():
            self._settings_win.lift()
            self._settings_win.focus_set()
            return

        # Discard any uncommitted edits from a previous open-then-close.
        # This must happen before building the widgets so every field
        # is initialised from the committed state.
        self._reset_setting_vars_from_committed()

        win = tk.Toplevel(self)
        win.title("Session Settings")
        win.minsize(560, 600)
        win.resizable(True, True)
        self._settings_win = win

        # ── Fixed banner (always visible, above the scroll area) ──────
        banner = tk.Frame(win, background="#fff8e1", padx=10, pady=6)
        banner.pack(side="top", fill="x")
        tk.Label(
            banner,
            text="✏️  Edit any setting below, then scroll down and click  ✓ Apply  to save and re-index.",
            background="#fff8e1",
            foreground="#5d4037",
            font=("TkDefaultFont", 9),
            anchor="w",
        ).pack(side="left")

        # ── Scrollable canvas inside the dialog ───────────────────────
        canvas = tk.Canvas(win, borderwidth=0, highlightthickness=0)
        sb = ttk.Scrollbar(win, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = ttk.Frame(canvas, padding=_PAD)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(win_id, width=e.width))

        # ── Mouse-wheel scrolling ─────────────────────────────────────
        # Strategy: bind the handler directly on every widget inside the dialog
        # rather than using bind_all.
        #
        # Why not bind_all?
        #   bind_all adds to tkinter's "all" binding tag, which fires *after*
        #   class-level handlers.  Text and Listbox widgets have class bindings
        #   for <MouseWheel> that can suppress propagation on some platforms,
        #   so bind_all may never fire when the cursor is over those widgets.
        #
        # Why fix the delta calculation?
        #   On Windows/physical mouse wheel event.delta is ±120 per notch, so
        #   dividing by 120 gives ±1.  On macOS trackpad event.delta is a small
        #   integer (±1…±30 per gesture frame), and int(±10 / 120) == 0 — nothing
        #   scrolls.  We normalise so at least 1 unit is always scrolled.

        def _on_mousewheel(event: tk.Event) -> None:
            try:
                delta = event.delta
                if delta == 0:
                    return
                # Large delta → physical scroll wheel (Windows-style ±120 per notch).
                # Small delta → macOS trackpad continuous scroll.
                if abs(delta) >= 120:
                    units = int(-delta / 120)
                else:
                    units = -1 if delta > 0 else 1
                canvas.yview_scroll(units, "units")
            except tk.TclError:
                pass  # canvas already destroyed

        def _bind_mousewheel(widget: tk.Widget) -> None:
            """Recursively bind the scroll handler on *widget* and all descendants."""
            try:
                widget.bind("<MouseWheel>", _on_mousewheel, add=True)
            except tk.TclError:
                pass
            for child in widget.winfo_children():
                _bind_mousewheel(child)

        # Bind on the canvas and the banner immediately (they exist now).
        canvas.bind("<MouseWheel>", _on_mousewheel, add=True)
        banner.bind("<MouseWheel>", _on_mousewheel, add=True)

        # Bind on the inner frame and everything inside it after the dialog is
        # fully built (after_idle runs once the event loop returns).
        win.after_idle(lambda: _bind_mousewheel(inner))

        # No global bind_all needed — destroying the Toplevel removes all
        # widget-level bindings automatically, so no explicit cleanup required.
        # Keep the Destroy handler only to catch any edge-case canvas errors.
        def _on_settings_destroy(event: tk.Event) -> None:
            pass  # instance bindings are cleaned up automatically with the widgets

        win.bind("<Destroy>", _on_settings_destroy)

        inner.columnconfigure(0, weight=1)
        row = 0

        # ── Model Selection ───────────────────────────────────────────
        mf = ttk.LabelFrame(inner, text="Model", padding=_PAD)
        mf.grid(row=row, column=0, sticky="ew", pady=(0, _PAD))
        mf.columnconfigure(1, weight=1)
        row += 1

        ttk.Label(mf, text="Provider:").grid(
            row=0, column=0, sticky="w", padx=(0, 8))
        provider_cb = ttk.Combobox(
            mf, textvariable=self._llm_provider_var,
            values=["gemini", "openai", "deepseek"],
            state="readonly", width=12)
        provider_cb.grid(row=0, column=1, sticky="w")
        provider_cb.bind("<<ComboboxSelected>>", self._on_provider_changed)

        ttk.Label(mf, text="Model:").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
        self._model_cb = ttk.Combobox(
            mf, textvariable=self._llm_model_var, width=22)
        self._model_cb.grid(row=1, column=1, sticky="w", pady=(6, 0))
        self._update_model_list()   # populate for current provider

        # ── API Key (single row, changes with provider) ───────────────
        akf = ttk.LabelFrame(inner, text="API Key", padding=_PAD)
        akf.grid(row=row, column=0, sticky="ew", pady=(0, _PAD))
        akf.columnconfigure(1, weight=1)
        row += 1

        self._api_key_label_var = tk.StringVar(value="Google API Key:")
        ttk.Label(akf, textvariable=self._api_key_label_var).grid(
            row=0, column=0, sticky="w", padx=(0, 8))

        # Single entry — textvariable is swapped by _update_api_key_row()
        self._active_key_entry = ttk.Entry(akf, show="*")
        self._active_key_entry.grid(row=0, column=1, sticky="ew", padx=(0, 4))

        self._api_key_show_btn = ttk.Button(
            akf, text="Show", width=5,
            command=lambda: self._toggle_key_entry(
                self._active_key_entry, self._api_key_show_btn))
        self._api_key_show_btn.grid(row=0, column=2)

        self._api_key_hint_var = tk.StringVar()
        self._api_key_hint_lbl = ttk.Label(
            akf, textvariable=self._api_key_hint_var,
            font=("TkDefaultFont", 9))
        self._api_key_hint_lbl.grid(row=0, column=3, padx=(6, 0))

        # Wire entry to current provider's var and update hint
        self._update_api_key_row()

        # ── Embedding ─────────────────────────────────────────────────────
        embf = ttk.LabelFrame(inner, text="Embedding", padding=_PAD)
        embf.grid(row=row, column=0, sticky="ew", pady=(0, _PAD))
        embf.columnconfigure(1, weight=1)
        row += 1

        ttk.Label(embf, text="Provider:").grid(
            row=0, column=0, sticky="w", padx=(0, 8))
        emb_cb = ttk.Combobox(
            embf, textvariable=self._emb_provider_disp_var,
            values=list(self._EMB_PROVIDER_OPTIONS.keys()),
            state="readonly", width=34)
        emb_cb.grid(row=0, column=1, sticky="w")
        emb_cb.bind("<<ComboboxSelected>>", lambda _e: self._on_emb_provider_changed())

        # Context row — swapped by _on_emb_provider_changed()
        self._emb_context_frame = ttk.Frame(embf)
        self._emb_context_frame.grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self._emb_context_frame.columnconfigure(1, weight=1)
        self._rebuild_emb_context()   # populate for current provider

        # ── Course Information ─────────────────────────────────────────
        inf = ttk.LabelFrame(inner, text="Course Information", padding=_PAD)
        inf.grid(row=row, column=0, sticky="ew", pady=(0, _PAD))
        inf.columnconfigure(1, weight=1)
        row += 1

        fields = [
            ("Course Name *", "red",   self._course_name_var),
            ("University",    "black", self._university_var),
            ("Course Dept",   "black", self._major_var),
            ("Course Code",   "black", self._course_code_var),
            ("Professor",     "black", self._professor_var),
            ("Semester",      "black", self._semester_var),
        ]
        for fi, (lbl, fg, var) in enumerate(fields):
            ttk.Label(inf, text=lbl + ":", foreground=fg).grid(
                row=fi, column=0, sticky="w", padx=(0, 6), pady=(3, 0))
            e = ttk.Entry(inf, textvariable=var)
            e.grid(row=fi, column=1, sticky="ew", pady=(3, 0))
            if lbl.startswith("Course Name"):
                self._course_name_entry = e

        # ── Exam Options ──────────────────────────────────────────────
        ef = ttk.LabelFrame(inner, text="Exam Options", padding=_PAD)
        ef.grid(row=row, column=0, sticky="ew", pady=(0, _PAD))
        ef.columnconfigure(1, weight=1)
        row += 1

        ttk.Label(ef, text="Exam type:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Combobox(ef, textvariable=self._exam_type_var,
                     values=[e.value for e in ExamType],
                     state="readonly", width=14
                     ).grid(row=0, column=1, sticky="w")

        ttk.Label(ef, text="Exam format:").grid(row=1, column=0, sticky="w",
                                                padx=(0, 6), pady=(4, 0))
        ttk.Combobox(ef, textvariable=self._exam_format_var,
                     values=[e.value for e in ExamFormat],
                     state="readonly", width=14
                     ).grid(row=1, column=1, sticky="w", pady=(4, 0))

        ttk.Label(ef, text="Exam duration:").grid(row=2, column=0, sticky="w",
                                                  padx=(0, 6), pady=(4, 0))
        ttk.Entry(ef, textvariable=self._exam_duration_var).grid(
            row=2, column=1, sticky="ew", pady=(4, 0))

        ttk.Label(ef, text="Exam info sheet:").grid(row=3, column=0, sticky="w",
                                                    padx=(0, 6), pady=(4, 0))
        ei_row = ttk.Frame(ef)
        ei_row.grid(row=3, column=1, sticky="ew", pady=(4, 0))
        ei_row.columnconfigure(0, weight=1)
        self._exam_info_path_label = ttk.Label(
            ei_row, textvariable=self._exam_info_path_var,
            foreground="gray", anchor="w", text="No file selected")
        self._exam_info_path_label.grid(row=0, column=0, sticky="ew")
        ttk.Button(ei_row, text="Browse...", width=8,
                   command=self._on_pick_exam_info
                   ).grid(row=0, column=1, padx=(4, 0))
        ttk.Button(ei_row, text="Clear", width=6,
                   command=self._on_clear_exam_info
                   ).grid(row=0, column=2, padx=(4, 0))

        # ── Workspace & Export ────────────────────────────────────────
        wf = ttk.LabelFrame(inner, text="Workspace & Export", padding=_PAD)
        wf.grid(row=row, column=0, sticky="ew", pady=(0, _PAD))
        wf.columnconfigure(1, weight=1)
        row += 1

        ttk.Label(wf, text="Workspace folder:").grid(
            row=0, column=0, sticky="w", padx=(0, 6))
        ws_row = ttk.Frame(wf)
        ws_row.grid(row=0, column=1, sticky="ew")
        ws_row.columnconfigure(0, weight=1)
        if self._workspace_committed:
            # Locked: show the path as a read-only label + Open button
            path_text = self._workspace_var.get() or str(get_app_data_dir())
            ttk.Label(ws_row, text=path_text, foreground="#1a56a5",
                      anchor="w").grid(row=0, column=0, sticky="ew")
            ttk.Button(ws_row, text="Open", width=6,
                       command=lambda: _open_folder_in_os(path_text)
                       ).grid(row=0, column=1, padx=(4, 0))
            ttk.Label(ws_row, text="🔒", foreground="gray"
                      ).grid(row=0, column=2, padx=(4, 0))
        else:
            # Not yet committed: allow user to pick
            self._workspace_label = ttk.Label(
                ws_row, textvariable=self._workspace_var,
                foreground="gray", anchor="w", text="Auto (app data folder)")
            self._workspace_label.grid(row=0, column=0, sticky="ew")
            ttk.Button(ws_row, text="Browse...", width=9,
                       command=self._on_pick_workspace
                       ).grid(row=0, column=1, padx=(4, 0))
            ttk.Button(ws_row, text="Reset", width=6,
                       command=self._on_reset_workspace
                       ).grid(row=0, column=2, padx=(4, 0))

        # ── Deletion warning ──────────────────────────────────────────
        warn_frame = tk.Frame(wf, background="#fff3e0",
                              highlightbackground="#e65100",
                              highlightthickness=1,
                              padx=8, pady=5)
        warn_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 2))
        tk.Label(
            warn_frame,
            text="⚠️  Deletion warning",
            background="#fff3e0", foreground="#bf360c",
            font=("TkDefaultFont", 9, "bold"),
            anchor="w",
        ).pack(side="top", fill="x")
        tk.Label(
            warn_frame,
            text=(
                "When this session is deleted, the agent bundle (.uacragent/) inside "
                "the workspace folder — including all session history, the vector store, "
                "generated outputs, and uploaded file copies — is permanently removed.\n"
                "If the workspace folder is empty afterwards, the folder itself is also deleted.\n"
                "If you choose a folder that already contains your own files, those files are "
                "not affected — only .uacragent/ is removed."
            ),
            background="#fff3e0", foreground="#4e342e",
            font=("TkDefaultFont", 9),
            anchor="w", justify="left", wraplength=460,
        ).pack(side="top", fill="x")

        ttk.Label(wf, text="Export format:").grid(
            row=2, column=0, sticky="w", padx=(0, 6), pady=(6, 0))
        ttk.Combobox(wf, textvariable=self._export_format_var,
                     values=[e.value for e in ExportFormat],
                     state="readonly", width=12
                     ).grid(row=2, column=1, sticky="w", pady=(6, 0))

        ttk.Label(wf, text="Extra instructions:").grid(
            row=3, column=0, sticky="nw", padx=(0, 6), pady=(6, 0))
        self._extra_text = tk.Text(wf, height=3, wrap="word")
        self._extra_text.grid(row=3, column=1, sticky="ew", pady=(6, 0))
        self._extra_text.insert("1.0", self._extra_instructions_var.get())

        # ── Course Documents ──────────────────────────────────────────
        docs_frame = ttk.LabelFrame(inner, text="Course Documents", padding=_PAD)
        docs_frame.grid(row=row, column=0, sticky="ew", pady=(0, _PAD))
        docs_frame.columnconfigure(0, weight=1)
        row += 1

        # Re-build file listboxes (they live inside this Toplevel)
        self._file_listboxes = {}
        for doc_type in DocumentType:
            self._create_doc_section(docs_frame, doc_type)
        # Populate listboxes from current session
        for dt, paths in self._session.classified_files.items():
            lb = self._file_listboxes.get(dt)
            if lb:
                lb.delete(0, tk.END)
                for p in paths:
                    lb.insert(tk.END, Path(p).name)

        # ── Bottom buttons ────────────────────────────────────────────
        btn_row_frame = ttk.Frame(inner)
        btn_row_frame.grid(row=row, column=0, sticky="ew", pady=(0, _PAD))
        btn_row_frame.columnconfigure(0, weight=1)
        row += 1

        self._settings_status_var = tk.StringVar(value="")
        ttk.Label(btn_row_frame, textvariable=self._settings_status_var,
                  foreground="gray", font=("TkDefaultFont", 9),
                  wraplength=440
                  ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        action_row = ttk.Frame(btn_row_frame)
        action_row.grid(row=1, column=0, sticky="ew")
        ttk.Button(action_row, text="✓  Apply",
                   command=self._on_apply_settings
                   ).pack(side="left", padx=(0, 8))
        ttk.Button(action_row, text="Close",
                   command=win.destroy
                   ).pack(side="right")

    def _create_doc_section(self, parent: ttk.Frame,
                            doc_type: DocumentType) -> None:
        label = _DOC_TYPE_LABELS.get(doc_type, doc_type.value)
        frame = ttk.LabelFrame(parent, text=label, padding=4)
        frame.pack(fill="x", pady=3)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1, minsize=55)
        frame.rowconfigure(1, weight=0, minsize=28)

        lb = tk.Listbox(frame, height=3, selectmode=tk.EXTENDED)
        sb = ttk.Scrollbar(frame, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self._file_listboxes[doc_type] = lb

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=1, column=0, columnspan=2, sticky="w", pady=(3, 4))
        ttk.Button(btn_row, text="Add...", width=7,
                   command=lambda dt=doc_type: self._on_add_files(dt)
                   ).pack(side="left", padx=(0, 3))
        ttk.Button(btn_row, text="Remove", width=7,
                   command=lambda dt=doc_type: self._on_remove_files(dt)
                   ).pack(side="left")

    # ------------------------------------------------------------------
    # App Settings dialog  (global, not per-session)
    # ------------------------------------------------------------------

    def _open_app_settings(self) -> None:
        """Open a small dialog to configure the global app data directory."""
        win = tk.Toplevel(self)
        win.title("App Settings")
        win.resizable(False, False)
        win.grab_set()

        frm = ttk.Frame(win, padding=16)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="App data folder:", font=("TkDefaultFont", 10, "bold")
                  ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        ttk.Label(
            frm,
            text="The index.json and any auto-created session workspaces\n"
                 "are stored here.  Changes take effect on next launch.",
            foreground="gray", font=("TkDefaultFont", 9),
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 10))

        # Current path entry
        path_var = tk.StringVar(value=self._app_data_dir_var.get())
        path_entry = ttk.Entry(frm, textvariable=path_var, width=42)
        path_entry.grid(row=2, column=0, sticky="ew", padx=(0, 4))

        def _browse() -> None:
            folder = filedialog.askdirectory(
                title="Select app data folder",
                initialdir=path_var.get() or str(Path.home()),
            )
            if folder:
                path_var.set(folder)

        ttk.Button(frm, text="Browse…", command=_browse
                   ).grid(row=2, column=1, padx=(0, 4))

        def _save() -> None:
            chosen = path_var.get().strip()
            if not chosen:
                messagebox.showwarning("Invalid Path",
                                       "Please enter a valid folder path.",
                                       parent=win)
                return
            p = Path(chosen)
            try:
                p.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                messagebox.showerror("Cannot Create Folder", str(exc), parent=win)
                return
            set_app_data_dir(p)
            self._app_data_dir_var.set(str(p.resolve()))
            messagebox.showinfo(
                "App Settings Saved",
                f"App data folder set to:\n{p.resolve()}\n\n"
                "Restart the application for the change to take full effect.",
                parent=win,
            )
            win.destroy()

        btn_row = ttk.Frame(frm)
        btn_row.grid(row=3, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(btn_row, text="Save", command=_save).pack(side="left", padx=(0, 6))
        ttk.Button(btn_row, text="Cancel", command=win.destroy).pack(side="left")

    # ------------------------------------------------------------------
    # Settings field helpers
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Provider / model helpers
    # ------------------------------------------------------------------

    def _settings_alive(self) -> bool:
        """Return True only when the Settings Toplevel exists and is not destroyed."""
        return (
            self._settings_win is not None
            and self._settings_win.winfo_exists()
        )

    def _update_model_list(self) -> None:
        """Refresh the model combobox values for the current provider.

        Skips the widget update when the Settings dialog is closed — the
        StringVars are always updated so the next dialog open picks the
        correct value.
        """
        provider = self._llm_provider_var.get()
        models = self._PROVIDER_MODELS.get(provider, [])
        # Always keep the StringVar consistent (no widget needed)
        current = self._llm_model_var.get()
        if current not in models and models:
            self._llm_model_var.set(models[0])
        # Only touch the Combobox widget if the dialog is alive
        if self._settings_alive() and hasattr(self, "_model_cb"):
            try:
                self._model_cb.configure(values=models)
            except tk.TclError:
                pass  # widget destroyed between the check and the call

    def _update_api_key_row(self) -> None:
        """Swap the active key entry to match the current provider.

        Safe to call even when the Settings dialog is closed.
        """
        # Label var is a plain StringVar — always safe to update
        provider = self._llm_provider_var.get()
        labels = {"gemini": "Google API Key:", "openai": "OpenAI API Key:",
                  "deepseek": "DeepSeek API Key:"}
        self._api_key_label_var.set(labels.get(provider, "API Key:"))

        # Update hint var (also a plain StringVar)
        env_var = self._PROVIDER_KEY_ENV.get(provider, "GOOGLE_API_KEY")
        env_key = os.environ.get(env_var, "").strip()
        self._api_key_hint_var.set("Loaded from .env" if env_key else "Not set")

        # Widget-level updates only when the dialog is alive
        if not self._settings_alive():
            return
        try:
            var_map = {
                "gemini":   self._gemini_key_var,
                "openai":   self._openai_key_var,
                "deepseek": self._deepseek_key_var,
            }
            var = var_map.get(provider, self._gemini_key_var)
            self._active_key_entry.configure(textvariable=var, show="*")
            self._api_key_show_btn.configure(text="Show")
            self._api_key_hint_lbl.configure(
                foreground="gray" if env_key else "#cc4400")
        except tk.TclError:
            pass  # widget destroyed between the check and the call

    def _on_emb_provider_changed(self) -> None:
        """Sync internal var from display var and rebuild the context row."""
        display = self._emb_provider_disp_var.get()
        internal = self._EMB_PROVIDER_OPTIONS.get(display, "gemini")
        self._emb_provider_var.set(internal)
        if self._settings_alive() and hasattr(self, "_emb_context_frame"):
            try:
                self._rebuild_emb_context()
            except tk.TclError:
                pass

    def _rebuild_emb_context(self) -> None:
        """Destroy and recreate the content of the embedding context frame."""
        frame = self._emb_context_frame
        for child in frame.winfo_children():
            child.destroy()
        frame.columnconfigure(1, weight=1)

        provider = self._emb_provider_var.get()

        if provider == "local":
            # Free model selector
            ttk.Label(frame, text="Model:").grid(
                row=0, column=0, sticky="w", padx=(0, 8))
            local_cb = ttk.Combobox(
                frame, textvariable=self._local_model_disp_var,
                values=list(self._FREE_EMB_MODELS.keys()),
                state="readonly", width=46)
            local_cb.grid(row=0, column=1, sticky="w")
            local_cb.bind("<<ComboboxSelected>>",
                          lambda _e: self._local_model_var.set(
                              self._FREE_EMB_MODELS.get(
                                  self._local_model_disp_var.get(), "all-MiniLM-L6-v2")))
            ttk.Label(
                frame,
                text="Downloaded from HuggingFace on first use, then cached in the app data folder. "
                     "Subsequent uses are instant with no internet required.",
                foreground="gray", font=("TkDefaultFont", 9), wraplength=400,
            ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(3, 0))
        else:
            # API-based: show a key entry field for the embedding provider.
            # Reuses the same StringVar as the LLM key section so both fields
            # stay in sync when the user types in either one.
            env_var = "GOOGLE_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
            key_var = self._gemini_key_var if provider == "gemini" else self._openai_key_var
            label   = "Google API Key:" if provider == "gemini" else "OpenAI API Key:"

            frame.columnconfigure(1, weight=1)
            ttk.Label(frame, text=label).grid(
                row=0, column=0, sticky="w", padx=(0, 8))

            emb_entry = ttk.Entry(frame, textvariable=key_var, show="*")
            emb_entry.grid(row=0, column=1, sticky="ew", padx=(0, 4))

            show_btn_cell: list[ttk.Button] = []
            show_btn_cell.append(ttk.Button(
                frame, text="Show", width=5,
                command=lambda: self._toggle_key_entry(emb_entry, show_btn_cell[0])))
            show_btn_cell[0].grid(row=0, column=2)

            # Status hint below the entry
            key_present = bool(os.environ.get(env_var, "").strip())
            if key_present:
                hint = f"✓  {env_var} loaded from .env"
                fg   = "gray"
            else:
                hint = f"⚠  {env_var} not set — enter it above or choose Free — Local."
                fg   = "#cc4400"
            ttk.Label(frame, text=hint, foreground=fg,
                      font=("TkDefaultFont", 9), wraplength=400,
                      ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(3, 0))

    def _has_embedding_key(self) -> bool:
        """Return True if the chosen embedding provider has what it needs."""
        provider = self._emb_provider_var.get()
        if provider == "local":
            return True  # no key required
        if provider == "openai":
            return bool(os.environ.get("OPENAI_API_KEY", "").strip())
        # gemini (default)
        return bool(os.environ.get("GOOGLE_API_KEY", "").strip())

    @staticmethod
    def _is_model_cached(model_name: str) -> bool:
        """Return True if the HuggingFace model is already in the local cache.

        Uses ``huggingface_hub.scan_cache_dir()`` when available.  Falls back
        to False (assume not cached) if the package is absent or the scan fails,
        which causes the confirmation dialog to appear — safer than silently
        skipping it.
        """
        try:
            from huggingface_hub import scan_cache_dir  # type: ignore[import]
            cached_ids = {repo.repo_id for repo in scan_cache_dir().repos}
            # Short names (e.g. "all-MiniLM-L6-v2") live under sentence-transformers/
            full_name = model_name if "/" in model_name else f"sentence-transformers/{model_name}"
            return full_name in cached_ids
        except Exception:
            return False  # conservative: prompt the user

    def _confirm_model_download(self) -> bool:
        """Show a confirmation dialog before downloading a local embedding model.

        Returns True if the user confirmed (or the model is already cached),
        False if the user cancelled.  Only relevant when embedding_provider == "local".
        """
        if self._emb_provider_var.get() != "local":
            return True

        model_name = self._local_model_var.get()
        if self._is_model_cached(model_name):
            return True  # already on disk — no need to ask

        # Work out display size from the label string
        import re as _re
        disp = self._local_model_disp_var.get()
        size_match = _re.search(r"~([\d.]+ MB)", disp)
        size_str = size_match.group(1) if size_match else "unknown size"

        from uacragent.infra.persistence import get_hf_cache_dir
        cache_dir = get_hf_cache_dir()

        return messagebox.askyesno(
            "Download Embedding Model",
            f'The embedding model has not been downloaded yet.\n\n'
            f'  Model : {model_name}\n'
            f'  Size  : {size_str}\n'
            f'  Saved to : {cache_dir}\n\n'
            f'This is a one-time download. Future uses load from the local cache '
            f'with no internet connection required.\n\n'
            f'Download and continue?',
            default=messagebox.YES,
            icon=messagebox.QUESTION,
        )

    def _on_provider_changed(self, _event: object = None) -> None:
        self._update_model_list()
        self._update_api_key_row()

    @staticmethod
    def _toggle_key_entry(entry: ttk.Entry, btn: ttk.Button | None = None) -> None:
        if entry.cget("show") == "*":
            entry.configure(show="")
            if btn:
                btn.configure(text="Hide")
        else:
            entry.configure(show="*")
            if btn:
                btn.configure(text="Show")

    def _on_pick_exam_info(self) -> None:
        path = filedialog.askopenfilename(
            title="Select exam information sheet file",
            filetypes=[("All supported", "*.pdf *.txt *.md *.docx"),
                       ("PDF", "*.pdf"), ("Text", "*.txt"),
                       ("Markdown", "*.md"), ("Word", "*.docx")])
        if path:
            self._exam_info_path_var.set(path)
            if hasattr(self, "_exam_info_path_label"):
                self._exam_info_path_label.configure(foreground="black")

    def _on_clear_exam_info(self) -> None:
        self._exam_info_path_var.set("")
        if hasattr(self, "_exam_info_path_label"):
            self._exam_info_path_label.configure(foreground="gray")

    def _on_pick_workspace(self) -> None:
        folder = filedialog.askdirectory(title="Select workspace folder")
        if folder:
            self._workspace_var.set(folder)
            if hasattr(self, "_workspace_label"):
                self._workspace_label.configure(foreground="black")

    def _on_reset_workspace(self) -> None:
        self._workspace_var.set("")
        if hasattr(self, "_workspace_label"):
            self._workspace_label.configure(foreground="gray")

    def _on_add_files(self, doc_type: DocumentType) -> None:
        paths = filedialog.askopenfilenames(
            title=f"Select {_DOC_TYPE_LABELS.get(doc_type, doc_type.value)} files",
            filetypes=_SUPPORTED_FILETYPES)
        lb = self._file_listboxes.get(doc_type)
        if lb is None:
            return
        existing = self._session.classified_files.setdefault(doc_type, [])
        for p in paths:
            if p not in existing:
                existing.append(p)
                lb.insert(tk.END, Path(p).name)

    def _on_remove_files(self, doc_type: DocumentType) -> None:
        lb = self._file_listboxes.get(doc_type)
        if lb is None:
            return
        indices = list(lb.curselection())
        files = self._session.classified_files.get(doc_type, [])
        for i in reversed(indices):
            lb.delete(i)
            if i < len(files):
                files.pop(i)

    # ------------------------------------------------------------------
    # Sync settings vars → session object
    # ------------------------------------------------------------------

    def _sync_session_from_vars(self) -> None:
        s = self._session
        s.llm_provider   = self._llm_provider_var.get()
        s.llm_model      = self._llm_model_var.get()
        s.course_name    = self._course_name_var.get().strip()
        s.university_name = self._university_var.get().strip()
        s.major          = self._major_var.get().strip()
        s.course_code    = self._course_code_var.get().strip()
        s.professor_name = self._professor_var.get().strip()
        s.semester       = self._semester_var.get().strip()
        s.exam_type      = self._exam_type_var.get()
        s.exam_format    = self._exam_format_var.get()
        s.exam_duration  = self._exam_duration_var.get().strip()
        s.exam_info_path = self._exam_info_path_var.get().strip()

        # Extra instructions (from Text widget if settings dialog is open)
        if self._settings_alive() and hasattr(self, "_extra_text"):
            try:
                s.extra_instructions = self._extra_text.get("1.0", tk.END).strip()
            except tk.TclError:
                s.extra_instructions = self._extra_instructions_var.get().strip()
        else:
            s.extra_instructions = self._extra_instructions_var.get().strip()

        chosen = self._workspace_var.get().strip()
        if chosen:
            # User explicitly picked a folder — use it directly.
            # workspace_id is irrelevant when workspace_folder is set.
            s.workspace_folder = Path(chosen)
        else:
            # No folder picked yet — leave workspace_folder as None so the
            # auto-assign in _on_load_session() can use the session's UUID-based
            # workspace_id to build a unique path under <app_data>/sessions/.
            # Never overwrite workspace_id here: doing so would collapse every
            # unspecified session onto the same "default" folder.
            s.workspace_folder = None

    def _sync_vars_from_session(self) -> None:
        """Push session data back into all StringVars (after switching sessions)."""
        s = self._session
        self._llm_provider_var.set(s.llm_provider or "gemini")
        self._llm_model_var.set(s.llm_model or "gemini-2.5-flash")
        self._update_model_list()
        self._course_name_var.set(s.course_name)
        self._university_var.set(s.university_name)
        self._major_var.set(s.major)
        self._course_code_var.set(s.course_code)
        self._professor_var.set(s.professor_name)
        self._semester_var.set(s.semester)
        self._exam_type_var.set(s.exam_type)
        self._exam_format_var.set(s.exam_format)
        self._exam_duration_var.set(s.exam_duration)
        self._exam_info_path_var.set(s.exam_info_path)
        self._workspace_var.set(str(s.workspace_folder) if s.workspace_folder else "")

        if self._settings_alive() and hasattr(self, "_extra_text"):
            try:
                self._extra_text.delete("1.0", tk.END)
                self._extra_text.insert("1.0", s.extra_instructions)
            except tk.TclError:
                self._extra_instructions_var.set(s.extra_instructions)
        else:
            self._extra_instructions_var.set(s.extra_instructions)

        # Repopulate file listboxes only when the settings dialog is alive.
        if self._settings_alive():
            for dt, lb in self._file_listboxes.items():
                try:
                    lb.delete(0, tk.END)
                    for p in self._session.classified_files.get(dt, []):
                        lb.insert(tk.END, Path(p).name)
                except tk.TclError:
                    pass  # widget destroyed — rebuilt on next dialog open

    # ------------------------------------------------------------------
    # API key
    # ------------------------------------------------------------------

    def _inject_api_keys(self) -> bool:
        """Inject all GUI keys + embedding settings into env.

        Returns True if the active LLM provider has its required key.
        """
        key_map = {
            "GOOGLE_API_KEY":   self._gemini_key_var.get().strip(),
            "OPENAI_API_KEY":   self._openai_key_var.get().strip(),
            "DEEPSEEK_API_KEY": self._deepseek_key_var.get().strip(),
        }
        changed = False
        for env_var, value in key_map.items():
            if value and value != os.environ.get(env_var, ""):
                os.environ[env_var] = value
                changed = True
        if changed:
            self._agent = None  # force re-creation with new keys

        # Propagate LLM provider/model
        provider = self._llm_provider_var.get()
        model = self._llm_model_var.get()
        if provider:
            os.environ["LLM_PROVIDER"] = provider
        if model:
            os.environ["LLM_MODEL"] = model

        # Propagate embedding provider and (if local) the model name
        emb_provider = self._emb_provider_var.get() or "gemini"
        os.environ["EMBEDDING_PROVIDER"] = emb_provider
        if emb_provider == "local":
            local_model = self._local_model_var.get() or "all-MiniLM-L6-v2"
            os.environ["LOCAL_EMBEDDING_MODEL"] = local_model

        # Check that the active LLM provider has its key
        env_var = self._PROVIDER_KEY_ENV.get(provider, "GOOGLE_API_KEY")
        return bool(os.environ.get(env_var, ""))

    # Keep old name used in a few places
    def _inject_api_key(self) -> bool:
        return self._inject_api_keys()

    def _get_agent(self) -> ConversationAgent:
        if self._agent is None:
            from uacragent.infra.settings import get_settings
            self._agent = ConversationAgent(get_settings())
        return self._agent

    # ------------------------------------------------------------------
    # Session list management
    # ------------------------------------------------------------------

    def _refresh_session_list(self) -> None:
        self._session_records = list_sessions()
        lb = self._session_listbox
        lb.delete(0, tk.END)
        for rec in self._session_records:
            # display_name (user-set) takes priority over course_name
            name = (rec.get("display_name")
                    or rec.get("course_name")
                    or Path(rec["workspace"]).name)
            date = _fmt_dt(rec.get("last_modified", ""))
            lb.insert(tk.END, f"  {name}\n  {date}" if date else f"  {name}")

        # Restore the listbox selection to the currently active session so that
        # the selection is not silently lost whenever the list is refreshed
        # (e.g. after indexing completes, after rename, after a chat auto-save).
        # Only do this when a committed session is actually active.
        if self._workspace_committed and self._session.workspace_folder:
            active = Path(self._session.workspace_folder).resolve()
            for i, rec in enumerate(self._session_records):
                if Path(rec.get("workspace", "")).resolve() == active:
                    lb.selection_set(i)
                    lb.see(i)
                    break

    def _on_session_select(self, _event: object = None) -> None:
        sel = self._session_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self._session_records):
            return
        ws = Path(self._session_records[idx]["workspace"])
        self._set_chat_active(True)
        # Load metadata + replay history immediately, then auto-index.
        self._load_session_from_workspace(ws)
        self._start_indexing(show_error_dialog=False)

    def _on_new_session(self) -> None:
        """Start a blank session and open settings so the user can fill it in."""
        self._session = AgentSession()
        self._session.chat_history = []
        self._workspace_committed = False  # new session: workspace not yet locked
        self._file_listboxes = {}          # clear stale widget refs
        self._init_setting_vars()          # reset all vars
        self._sync_vars_from_session()
        self._set_chat_active(True)
        self._header_course_var.set("New session")
        self._session_status_var.set("Fill in the settings and click Apply.")
        self._clear_chat()
        self._show_welcome()
        self._open_settings()

    def _on_delete_session(self) -> None:
        sel = self._session_listbox.curselection()
        if not sel:
            messagebox.showinfo("Delete Session", "Select a session to delete.")
            return
        idx = sel[0]
        if idx >= len(self._session_records):
            return
        rec = self._session_records[idx]
        name = rec.get("course_name") or Path(rec["workspace"]).name
        if not messagebox.askyesno(
            "Delete Session",
            f'Delete session "{name}"?\n\n'
            "This will permanently remove the .uacragent folder inside the "
            "workspace, which contains:\n"
            "  • Session history and settings\n"
            "  • Vector store (chroma_db)\n"
            "  • Generated outputs\n"
            "  • Uploaded file copies\n\n"
            "Your original source files are not affected."
        ):
            return
        ws = Path(rec["workspace"])
        delete_session(ws)
        # If the deleted session is the active one, return to a clean idle state.
        # _workspace_committed MUST be reset here — without it, _on_close() would
        # call _save_current_session() on the blank AgentSession(), creating a
        # phantom entry in the index that re-appears on the next launch.
        #
        # Compare using workspace_folder directly (the real committed path).
        # Falling back to _default_workspace() when workspace_folder is None would
        # produce a wrong path and silently skip this branch for UUID-based sessions.
        active_ws = self._session.workspace_folder
        if active_ws is not None and Path(active_ws).resolve() == ws.resolve():
            self._session = AgentSession()
            self._workspace_committed = False
            self._show_idle()
        self._refresh_session_list()

    def _on_rename_session(self, _event: object = None) -> None:
        sel = self._session_listbox.curselection()
        if not sel:
            messagebox.showinfo("Rename Session", "Select a session to rename.")
            return
        idx = sel[0]
        if idx >= len(self._session_records):
            return
        rec = self._session_records[idx]
        current_name = (rec.get("display_name")
                        or rec.get("course_name")
                        or Path(rec["workspace"]).name)
        new_name = simpledialog.askstring(
            "Rename Session",
            "Enter a new name for this session:",
            initialvalue=current_name,
            parent=self,
        )
        if new_name is None or not new_name.strip():
            return
        ws = Path(rec["workspace"])
        rename_session(ws, new_name.strip())
        # _refresh_session_list() re-selects the active session automatically.
        self._refresh_session_list()

    def _load_session_from_workspace(self, ws: Path) -> None:
        data = load_session(ws)
        if data is None:
            return
        self._session = dict_to_session(data)
        # Sessions loaded from disk already have a committed workspace.
        self._workspace_committed = True

        # Restore embedding settings (stored as ui_extras in session.json)
        emb_provider = data.get("embedding_provider", "gemini")
        local_model  = data.get("local_embedding_model", "all-MiniLM-L6-v2")
        self._emb_provider_var.set(emb_provider)
        self._emb_provider_disp_var.set(
            self._EMB_PROVIDER_DISPLAY.get(emb_provider, emb_provider))
        self._local_model_var.set(local_model)
        self._local_model_disp_var.set(
            self._FREE_EMB_MODEL_TO_DISPLAY.get(local_model, local_model))

        # Commit the embedding provider into os.environ immediately so that
        # Re-index (which does not go through Apply) uses the correct provider.
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

    def _default_workspace(self) -> Path:
        return (get_app_data_dir() / "sessions" / "default").resolve()

    # ------------------------------------------------------------------
    # Indexing  (shared core used by sidebar select, Apply, and Re-index)
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
        env_var = self._PROVIDER_KEY_ENV.get(provider, "GOOGLE_API_KEY")
        if not os.environ.get(env_var, "").strip():
            label = self._PROVIDER_KEY_LABEL.get(provider, "API Key")
            if show_error_dialog:
                messagebox.showwarning(
                    "API Key Required",
                    f"No {label} found for the selected LLM provider ({provider}).\n\n"
                    "Enter your key in ⚙ Settings → API Key, then click Apply.")
            else:
                self._append_chat(
                    "system",
                    f"⚠️ No {label} configured. Open ⚙ Settings → API Key to enter "
                    "one, then click Apply.")
            return

        if not self._has_embedding_key():
            if show_error_dialog:
                messagebox.showwarning(
                    "Embedding Key Required",
                    "Document indexing requires a Google or OpenAI API key for embeddings.\n\n"
                    "• Using Gemini or OpenAI as your LLM: the same key is used automatically.\n"
                    "• Using DeepSeek: enter a Gemini or OpenAI key in ⚙ Settings → Embedding.")
            else:
                self._append_chat(
                    "system",
                    "⚠️ Embedding key required. Open ⚙ Settings → Embedding to "
                    "configure, then click Apply.")
            return

        if not self._session.course_name:
            if show_error_dialog:
                messagebox.showwarning("Course Name Required",
                                       "Please enter a course name in ⚙ Settings.")
                self._open_settings()
            else:
                self._append_chat(
                    "system",
                    "⚠️ Course name required. Open ⚙ Settings to fill in course "
                    "details, then click Apply.")
            return

        if not self._session.has_files():
            self._append_chat(
                "system",
                "⚠️ No documents loaded. Add files in ⚙ Settings → Course Documents, "
                "then click Apply to index them.")
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
            busy_label = "Downloading embedding model… (this may take a while)"
        else:
            busy_label = "Indexing documents…"

        self._set_busy(True, busy_label)
        self._session_status_var.set(busy_label)
        self._append_chat("system", busy_label)

        _show_err = show_error_dialog

        def _work() -> None:
            def _progress(msg: str) -> None:
                if not self._cancel_event.is_set():
                    self.after(0, lambda m=msg: self._busy_label.configure(text=m))
                    self.after(0, lambda m=msg: self._session_status_var.set(m))

            try:
                agent = self._get_agent()
                msg = agent.initialize_session(self._session, progress_cb=_progress)
                if not self._cancel_event.is_set():
                    self.after(0, self._on_session_loaded, msg)
            except Exception as exc:
                if not self._cancel_event.is_set():
                    self.after(0, lambda e=str(exc): self._on_session_load_error(e, _show_err))

        threading.Thread(target=_work, daemon=True).start()

    def _on_load_session(self) -> None:
        """Manual Re-index button: re-index with currently *committed* settings.

        Settings are committed by Apply — this button does not pull in any
        uncommitted changes from the StringVars.
        """
        self._start_indexing(show_error_dialog=True)

    def _on_session_loaded(self, status: str) -> None:
        self._set_busy(False)
        self._update_header()
        self._session_status_var.set(status)
        if self._settings_alive():
            self._settings_status_var.set(status)
        # History is already visible — just append the completion notice.
        self._append_chat("system", f"✓ Documents indexed. {status}")
        self._save_current_session()
        self._refresh_session_list()

    def _on_session_load_error(self, error: str, show_dialog: bool = True) -> None:
        self._set_busy(False)
        self._session_status_var.set(f"Error: {error}")
        self._append_chat("system", f"⚠️ Indexing failed: {error}")
        if not show_dialog:
            return
        error_lower = error.lower()
        if any(k in error_lower for k in ("api key", "api_key", "invalid_argument",
                                           "authentication", "permission_denied",
                                           "unauthenticated")):
            detail = (
                "Your API key appears to be missing or invalid.\n\n"
                "Open ⚙ Settings → API Key, enter a valid key, and click Apply."
            )
        else:
            detail = "Check your file paths and network connection, then try again."
        messagebox.showerror(
            "Indexing Failed",
            f"Could not index session documents:\n\n{error}\n\n{detail}"
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
        env_var = self._PROVIDER_KEY_ENV.get(provider, "GOOGLE_API_KEY")
        if not os.environ.get(env_var, "").strip():
            label = self._PROVIDER_KEY_LABEL.get(provider, "API Key")
            messagebox.showwarning(
                "API Key Required",
                f"Enter your {label} in ⚙ Settings → API Key and click  ✓ Apply.")
            return
        if not self._session.course_name:
            messagebox.showwarning(
                "Course Name Required",
                "Please enter a course name in ⚙ Settings and click  ✓ Apply.")
            self._open_settings()
            return
        self._input_text.delete("1.0", tk.END)
        self._append_chat("user", message)
        self._set_busy(True, "Thinking…")

        def _work() -> None:
            def _progress(msg: str) -> None:
                if not self._cancel_event.is_set():
                    self.after(0, lambda m=msg: self._busy_label.configure(text=m))

            try:
                response = self._get_agent().chat(message, self._session,
                                                   progress_cb=_progress)
                if not self._cancel_event.is_set():
                    self.after(0, self._on_chat_response, response)
            except Exception as exc:
                if not self._cancel_event.is_set():
                    self.after(0, self._on_chat_error, str(exc))

        threading.Thread(target=_work, daemon=True).start()

    def _send_message(self, message: str) -> None:
        self._input_text.delete("1.0", tk.END)
        self._input_text.insert("1.0", message)
        self._on_send()

    def _on_chat_response(self, response: ChatResponse) -> None:
        self._set_busy(False)
        self._append_chat("assistant", response.text)
        if response.output_path:
            self._append_output_link(response.output_path, response.task_type)
        self._save_current_session()

    def _on_chat_error(self, error: str) -> None:
        self._set_busy(False)
        self._append_chat("system", f"⚠️ Error: {error}")
        error_lower = error.lower()
        if any(k in error_lower for k in ("api key", "api_key", "invalid_argument",
                                           "authentication", "permission_denied",
                                           "unauthenticated")):
            detail = (
                "Your API key appears to be missing or invalid.\n\n"
                "Open ⚙ Settings → API Key, enter a valid key, and click Apply."
            )
        else:
            detail = "You can try sending your message again."
        messagebox.showerror(
            "Response Failed",
            f"The agent could not complete your request:\n\n{error}\n\n{detail}"
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
        self._append_chat(
            "assistant",
            "Welcome! Open ⚙ Settings to fill in your course details and add "
            "documents, then click Apply to save and index them.\n\n"
            "After that you can ask me anything about the course or use the "
            "quick action buttons to generate study documents.",
        )

    def _replay_chat_history(self) -> None:
        """Re-render saved messages into the chat display. No status hints — those
        come from the indexing flow that follows immediately after."""
        from langchain_core.messages import HumanMessage, AIMessage
        for msg in self._session.chat_history:
            if isinstance(msg, HumanMessage):
                self._append_chat("user", msg.content)
            elif isinstance(msg, AIMessage):
                self._append_chat("assistant", msg.content)

    def _append_chat(self, role: str, text: str) -> None:
        self._chat_text.configure(state="normal")
        if role == "user":
            self._chat_text.insert(tk.END, "You\n", "user_label")
            self._chat_text.insert(tk.END, text + "\n", "user_body")
        elif role == "assistant":
            self._chat_text.insert(tk.END, "Assistant\n", "assistant_label")
            display = text.replace("**", "").replace("__", "")
            self._chat_text.insert(tk.END, display + "\n", "assistant_body")
        else:
            self._chat_text.insert(tk.END, text + "\n", "system_body")
        self._chat_text.configure(state="disabled")
        self._chat_text.see(tk.END)

    def _append_output_link(self, output_path: str, task_type: str | None) -> None:
        label = task_type.replace("_", " ").title() if task_type else "Output"
        self._chat_text.configure(state="normal")
        self._chat_text.insert(tk.END, f"\n📄 {label} generated: ", "assistant_body")

        tag_file = f"link_{id(output_path)}"
        self._chat_text.tag_configure(tag_file, foreground="#1565c0", underline=True)
        self._chat_text.tag_bind(tag_file, "<Button-1>",
                                 lambda _e, p=output_path: _open_file_in_os(p))
        self._chat_text.tag_bind(tag_file, "<Enter>",
                                 lambda _e: self._chat_text.configure(cursor="hand2"))
        self._chat_text.tag_bind(tag_file, "<Leave>",
                                 lambda _e: self._chat_text.configure(cursor=""))
        self._chat_text.insert(tk.END, Path(output_path).name, tag_file)

        self._chat_text.insert(tk.END, "  ", "assistant_body")
        tag_folder = f"folder_{id(output_path)}"
        self._chat_text.tag_configure(tag_folder, foreground="#555", underline=True)
        self._chat_text.tag_bind(tag_folder, "<Button-1>",
                                 lambda _e, p=output_path: _open_folder_in_os(
                                     str(Path(p).parent)))
        self._chat_text.tag_bind(tag_folder, "<Enter>",
                                 lambda _e: self._chat_text.configure(cursor="hand2"))
        self._chat_text.tag_bind(tag_folder, "<Leave>",
                                 lambda _e: self._chat_text.configure(cursor=""))
        self._chat_text.insert(tk.END, "[Open folder]", tag_folder)

        # Optional extra-format export
        export_fmt = self._export_format_var.get()
        if export_fmt != ExportFormat.markdown.value and output_path.endswith(".md"):
            try:
                ws = workspace_paths(
                    workspace_id=self._session.workspace_id,
                    workspace_folder=self._session.workspace_folder,
                )
                ensure_workspace_dirs(ws)
                md_text = Path(output_path).read_text(encoding="utf-8")
                extra_path = (save_docx(md_text, ws)
                              if export_fmt == ExportFormat.docx.value
                              else save_pdf(md_text, ws))
                self._chat_text.insert(tk.END, "\n", "assistant_body")
                xtag = f"extra_{id(extra_path)}"
                self._chat_text.tag_configure(xtag, foreground="#1565c0", underline=True)
                self._chat_text.tag_bind(xtag, "<Button-1>",
                                         lambda _e, p=extra_path: _open_file_in_os(p))
                self._chat_text.insert(
                    tk.END,
                    f"📥 {export_fmt.upper()} export: {Path(extra_path).name}", xtag)
            except Exception as exc:
                self._chat_text.insert(
                    tk.END, f"\n⚠️ Export failed: {exc}", "system_body")

        self._chat_text.insert(tk.END, "\n", "assistant_body")
        self._chat_text.configure(state="disabled")
        self._chat_text.see(tk.END)

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def _update_header(self) -> None:
        name = self._session.course_name or "Untitled session"
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

    def _on_apply_settings(self) -> None:
        """Save settings then re-index documents.

        Syncs all fields → session, injects API keys, persists to disk, and
        triggers a full re-index so every change (model, key, docs, embedding,
        course info) takes effect immediately.

        Session creation rule
        ---------------------
        A session is considered "created" — and therefore persisted — as soon as
        the user has filled in a course name and clicked Apply.  We do not wait
        for indexing to succeed; the session is committed immediately so it
        survives app restarts even when there are no files yet.
        """
        self._sync_session_from_vars()
        self._inject_api_keys()
        self._agent = None          # force re-creation with updated provider/model
        self._update_header()

        # ── Commit the session the moment Apply is clicked with a course name ──
        # Without this, _save_current_session() would be blocked by the
        # _workspace_committed guard for every new session that hasn't indexed yet
        # (e.g. no files added, or indexing still pending).
        if self._session.course_name and not self._workspace_committed:
            # Auto-assign workspace if the user didn't pick one explicitly.
            if not self._session.workspace_folder:
                self._session.workspace_folder = (
                    get_app_data_dir() / "sessions" / self._session.workspace_id
                )
                self._workspace_var.set(str(self._session.workspace_folder))
            self._workspace_committed = True

        self._save_current_session()
        self._refresh_session_list()
        if self._settings_alive():
            try:
                self._settings_status_var.set("Applying settings and re-indexing…")
            except tk.TclError:
                pass
        self._start_indexing(show_error_dialog=True)

    def _on_close(self) -> None:
        self._save_current_session()
        self.destroy()

    # ------------------------------------------------------------------
    # Busy state
    # ------------------------------------------------------------------

    def _set_busy(self, busy: bool, label: str = "") -> None:
        self._is_busy = busy
        self._send_btn.configure(state="disabled" if busy else "normal")
        self._load_btn.configure(state="disabled" if busy else "normal")
        self._busy_label.configure(text=label)
        if busy:
            self._cancel_event.clear()
            self._cancel_btn.pack(fill="x", pady=(2, 0))
        else:
            self._cancel_btn.pack_forget()


    def _on_cancel(self) -> None:
        """Signal the in-flight background request to be discarded."""
        self._cancel_event.set()
        self._set_busy(False)
        self._append_chat("system", "Request cancelled.")

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
    app = ConversationApp()
    app.mainloop()


if __name__ == "__main__":
    main()
