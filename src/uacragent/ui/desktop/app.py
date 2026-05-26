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
from tkinter import filedialog, ttk

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
    _WINDOW_TITLE, _MIN_WIDTH, _MIN_HEIGHT, _INIT_WIDTH, _INIT_HEIGHT,
    _PAD, _SESSION_LIST_WIDTH,
    _SUPPORTED_FILETYPES, _DOC_TYPE_LABELS, _QUICK_ACTIONS,
    _STRINGS, _THEME_COLORS, _FONT_SIZE_VALUES,
    _open_in_os, _open_file_in_os, _open_folder_in_os,
    _strip_markdown, _fmt_dt,
)
from ._custom_widgets import (
    AutoHideScrollbar, draw_rounded_rect,
    draw_left_rounded_rect, draw_right_rounded_rect,
    CustomSessionList, _RoundedChip, _SidebarIcon,
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
        import sys as _sys
        _assets = Path(__file__).parent.parent.parent.parent.parent / "assets"
        try:
            from PIL.ImageTk import PhotoImage as _PILPhotoImage

            if _sys.platform == "darwin":
                # macOS does NOT apply its squircle mask to programmatically-
                # set icons — only to proper .app bundle ICNS resources.
                # We therefore use the pre-rounded 512 px PNG (transparent
                # corners baked in) so the Dock shows a correctly shaped icon.
                # 512 px ensures macOS scales *down* to Dock size rather than
                # upscaling a small image, which previously caused it to look
                # slightly oversized.
                _icon_path = _assets / "logo_512.png"
                if not _icon_path.exists():
                    _icon_path = _assets / "logo_256.png"
            else:
                # Other platforms: 64 px pre-rounded image for the title bar.
                _icon_path = _assets / "logo_64.png"
                if not _icon_path.exists():
                    _icon_path = _assets / "logo_256.png"

            if _icon_path.exists():
                _icon_img = _PILPhotoImage(file=str(_icon_path))
                self.iconphoto(True, _icon_img)
                self._app_icon = _icon_img  # keep ref — prevents GC

            # macOS: also set the Dock icon via AppKit when pyobjc is
            # available — this is the most reliable path on macOS.
            if _sys.platform == "darwin":
                try:
                    from AppKit import NSApplication, NSImage  # type: ignore
                    _dock_path = _assets / "logo_512.png"
                    if not _dock_path.exists():
                        _dock_path = _assets / "logo_256.png"
                    if _dock_path.exists():
                        _ns_img = NSImage.alloc().initByReferencingFile_(
                            str(_dock_path)
                        )
                        NSApplication.sharedApplication().setApplicationIconImage_(
                            _ns_img
                        )
                except Exception:  # noqa: BLE001
                    pass  # pyobjc not installed — iconphoto path used instead
        except Exception:  # noqa: BLE001
            pass  # icon is cosmetic — never crash on failure

        # Centre the main window on the primary display before showing it.
        # withdraw() hides it so the user never sees it in the wrong position.
        self.withdraw()
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        # Use _INIT_WIDTH/_INIT_HEIGHT for the launch size; clamp to screen so
        # the window fits even on small displays.
        iw = min(_INIT_WIDTH,  sw - 40)
        ih = min(_INIT_HEIGHT, sh - 80)
        x = (sw - iw) // 2
        y = (sh - ih) // 2
        self.geometry(f"{iw}x{ih}+{x}+{y}")
        self.deiconify()

        # Active session
        self._session = AgentSession()
        self._agent: ConversationAgent | None = None
        self._is_busy = False
        self._cancel_event = threading.Event()  # set to abort in-flight requests

        # Sidebar collapse state
        self._sidebar_visible: bool = True
        self._saved_sash_pos: int = _SESSION_LIST_WIDTH

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
        # Single row/column — the PanedWindow fills the entire window.
        # The sidebar toggle icon lives inside the chat pane's top bar
        # (not in a separate global toolbar) so there is no wasted space.
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        _mode0 = self._color_mode_var.get() if hasattr(self, "_color_mode_var") else "light"

        # ── Content paned window ───────────────────────────────────────
        _wbg0 = _THEME_COLORS.get(_mode0, _THEME_COLORS["light"])["window_bg"]
        # sashwidth=8 gives a comfortable drag target; background=window_bg
        # makes it invisible — the chat card's curved left edge is the only
        # visible indicator of the resizable boundary.
        paned = tk.PanedWindow(self, orient="horizontal",
                               sashwidth=8, sashrelief="flat",
                               background=_wbg0)
        paned.grid(row=0, column=0, sticky="nsew")
        self._paned = paned

        self._build_session_list_pane()
        self._build_chat_pane()

    # ── Session list pane ─────────────────────────────────────────────

    def _build_session_list_pane(self) -> None:
        _mode0 = self._color_mode_var.get() if hasattr(self, "_color_mode_var") else "light"
        _c0    = _THEME_COLORS.get(_mode0, _THEME_COLORS["light"])
        _wbg   = _c0["window_bg"]
        _sbg   = _c0["sidebar_bg"]
        _fg    = _c0.get("lb_fg", "#1a2744")
        _st_fg = _c0.get("status_fg", "#9aa5be")
        _brd   = _c0.get("input_border", "#cdd4e8")
        _sz    = self._font_size() if hasattr(self, "_font_size_var") else 13

        # Sidebar sits directly on the window background — no card, no border.
        # The chat card's curved left edge is what visually separates the two.
        frame = tk.Frame(self._paned, bg=_wbg, width=_SESSION_LIST_WIDTH)
        frame.grid_propagate(False)
        # row 0: New Session chip    (fixed)
        # row 1: Search bar          (fixed)
        # row 2: "Sessions" label    (fixed)
        # row 3: session list        (expands)
        # row 4: thin separator      (fixed)
        # row 5: App Settings chip   (fixed)
        frame.rowconfigure(3, weight=1)
        frame.columnconfigure(0, weight=1)
        self._paned.add(frame, minsize=160, stretch="never")
        self._sidebar_frame = frame   # kept for _toggle_sidebar / _apply_theme

        # ── row 0: New Session chip (full-width, primary colour) ─────────────
        # _RoundedChip placed with sticky="ew" stretches to fill the column
        # because its <Configure> binding redraws the rounded rect at the new
        # canvas width — the creation-time width= is just a layout hint.
        self._new_session_btn = _RoundedChip(
            frame, text=self._t("new_session"),
            chip_bg=_wbg,
            chip_fg=_fg,
            parent_bg=_wbg,
            font=("TkDefaultFont", _sz, "bold"),
            padx=12, pady=7,
            hover_bg=_c0.get("lb_hover_bg", "#dfe4f0"),
            command=self._on_new_session,
            text_anchor="w",
        )
        self._new_session_btn.grid(row=0, column=0, sticky="ew",
                                   padx=8, pady=(8, 4))
        self._i18n_widgets.append((self._new_session_btn, "text", "new_session"))

        # ── row 1: Search bar (rounded canvas + Entry) ───────────────────────
        self._search_var = tk.StringVar()
        self._search_outer = tk.Frame(frame, bg=_wbg)
        self._search_outer.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 4))
        self._search_outer.columnconfigure(0, weight=1)

        # Canvas paints the rounded border; the Entry lives inside via
        # create_window.  _redraw_search_cv() is called on <Configure> and
        # after every theme/font change to keep colours and sizes in sync.
        self._search_cv = tk.Canvas(
            self._search_outer, bg=_wbg,
            highlightthickness=0, bd=0, height=30,
        )
        self._search_cv.grid(row=0, column=0, sticky="ew")

        self._search_entry = tk.Entry(
            self._search_cv,
            textvariable=self._search_var,
            bg=_c0.get("input_bg", _c0.get("lb_bg", "#e8ecf5")),
            fg=_fg,
            insertbackground=_fg,
            relief="flat", bd=0,
            font=("TkDefaultFont", max(_sz - 1, 10)),
            highlightthickness=0,
        )
        self._search_cv_win = self._search_cv.create_window(
            28, 4, anchor="nw", window=self._search_entry,
        )
        self._search_cv.bind("<Configure>", lambda _e: self._redraw_search_cv())
        self._search_var.trace_add("write", lambda *_: self._on_search_changed())
        # Clicking the search canvas (outside the Entry) moves focus away from
        # the Entry so stray keystrokes don't accumulate in the search box.
        self._search_cv.bind("<Button-1>", lambda _e: self.focus_set(), add="+")

        # ── row 2: "Sessions" section label ──────────────────────────────────
        self._sessions_label = tk.Label(
            frame, text=self._t("sessions"),
            bg=_wbg, fg=_st_fg,
            font=("TkDefaultFont", max(_sz - 2, 9)),
            anchor="w",
        )
        self._sessions_label.grid(row=2, column=0, sticky="ew",
                                   padx=12, pady=(0, 2))
        self._i18n_widgets.append((self._sessions_label, "text", "sessions"))

        # ── row 3: Rounded-corner session list (expands) ─────────────────────
        self._list_canvas = tk.Canvas(
            frame, bg=_wbg, highlightthickness=0, bd=0,
        )
        self._list_canvas.grid(row=3, column=0, sticky="nsew", padx=6, pady=2)

        self._list_inner = tk.Frame(self._list_canvas, bg=_c0["lb_bg"])
        self._list_inner.rowconfigure(0, weight=1)
        self._list_inner.columnconfigure(0, weight=1)
        self._list_canvas_id = self._list_canvas.create_window(
            3, 3, anchor="nw", window=self._list_inner,
        )
        self._list_canvas.bind(
            "<Configure>", lambda _e: self._redraw_list_canvas()
        )

        self._session_list = CustomSessionList(
            self._list_inner,
            on_select=self._on_session_select,
            on_rename=self._on_rename_session,
            on_delete=self._on_delete_session,
            colors=_c0,
            rename_label=self._t("rename"),
            delete_label=self._t("delete"),
        )
        self._session_list.grid(row=0, column=0, sticky="nsew")

        # ── row 4: thin 1-px separator ───────────────────────────────────────
        self._sidebar_sep = tk.Frame(frame, height=1, bg=_c0.get("input_border", "#cdd4e8"))
        self._sidebar_sep.grid(row=4, column=0, sticky="ew", padx=6)

        # ── row 5: App Settings — ghost chip (text always readable, bg blends
        # into sidebar; hover highlights the pill) ────────────────────────────
        # chip_bg == parent_bg → canvas is transparent, no pill visible until
        # hover.  The chip_fg text remains readable against the sidebar bg.
        self._gear_btn = _RoundedChip(
            frame, text=self._t("app_settings"),
            chip_bg=_wbg,
            chip_fg=_fg,
            parent_bg=_wbg,
            font=("TkDefaultFont", _sz),
            padx=10, pady=6,
            hover_bg=_c0.get("lb_hover_bg", "#dfe4f0"),
            command=self._open_app_settings,
            text_anchor="w",
        )
        self._gear_btn.grid(row=5, column=0, sticky="ew", padx=8, pady=(4, 8))
        self._i18n_widgets.append((self._gear_btn, "text", "app_settings"))

        # Keep the workspace list in sync with what we display.
        # _visible_records is the filtered subset shown in the list widget;
        # when no search is active it equals _session_records.
        self._session_records: list[dict] = []
        self._visible_records: list[dict] = []

    # ── Chat pane ─────────────────────────────────────────────────────

    def _build_chat_pane(self) -> None:
        # Use tk.Frame so bg=window_bg is reliable on macOS (ttk ignores bg).
        _mode0 = self._color_mode_var.get() if hasattr(self, "_color_mode_var") else "light"
        _wbg0  = _THEME_COLORS.get(_mode0, _THEME_COLORS["light"])["window_bg"]
        right = tk.Frame(self._paned, bg=_wbg0)
        # Single expanding row/column — _hist_canvas fills the entire pane.
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)
        self._paned.add(right, minsize=500, stretch="always")
        self._chat_frame = right   # kept so _toggle_sidebar can re-add it

        _mode0 = self._color_mode_var.get() if hasattr(self, "_color_mode_var") else "light"
        _c0 = _THEME_COLORS.get(_mode0, _THEME_COLORS["light"])

        # ── Rounded chat card ─────────────────────────────────────────────
        # _hist_canvas draws a rounded rectangle on the window background.
        # Margins (set in _redraw_hist_canvas) let the window_bg show around
        # the card on all sides except the left, where the sidebar content
        # sits.  _hist_inner holds all chat content inside the card.
        self._hist_canvas = tk.Canvas(
            right, bg=_c0["window_bg"],
            highlightthickness=0, bd=0,
        )
        self._hist_canvas.grid(row=0, column=0, sticky="nsew")

        # _hist_inner distributes height between all content rows:
        #   row 0 — top bar (toggle + title)     weight=0
        #   row 1 — chat history                 weight=1
        #   row 2 — input block                  weight=0
        # Separators are removed to give a clean, division-free card.
        _card_bg = _c0["text_bg"]
        self._hist_inner = tk.Frame(self._hist_canvas, bg=_card_bg)
        self._hist_inner.rowconfigure(0, weight=0)
        self._hist_inner.rowconfigure(1, weight=1)
        self._hist_inner.rowconfigure(2, weight=0)
        self._hist_inner.columnconfigure(0, weight=1)
        self._hist_canvas_win = self._hist_canvas.create_window(
            0, 0, anchor="nw", window=self._hist_inner,
        )
        self._hist_canvas.bind("<Configure>", lambda _: self._redraw_hist_canvas())
        self._hist_inner.bind("<Configure>",  lambda _: self._redraw_hist_canvas())

        # ── row 0 of _hist_inner: Top bar (sidebar toggle + title) ────────
        self._chat_top_bar = top_bar = tk.Frame(self._hist_inner, bg=_card_bg)
        top_bar.grid(row=0, column=0, sticky="ew", pady=(4, 0), padx=4)
        # top_bar grid: 2 rows, 2 cols.
        #   row 0 (weight=0) — toggle icon + session title, same row so they
        #                       share the same cell height and are centred together.
        #                       IMPORTANT: toggle must NOT use rowspan so its
        #                       canvas stays exactly as tall as the title row.
        #   row 1 (weight=0) — status label (busy / error), indented under title.
        top_bar.rowconfigure(0, weight=0)
        top_bar.rowconfigure(1, weight=0)
        top_bar.columnconfigure(1, weight=1)

        # Sidebar toggle — canvas-drawn icon; parent_bg=text_bg so the canvas
        # blends seamlessly into the white card with no artefact border.
        # Row 0 only (no rowspan) so the canvas height == row-0 height ==
        # title height, making the icon and title share the same vertical centre.
        self._toggle_sidebar_btn = _SidebarIcon(
            top_bar, command=self._toggle_sidebar, colors=_c0, parent_bg=_card_bg,
        )
        self._toggle_sidebar_btn.grid(row=0, column=0, padx=(0, 8), sticky="ns")

        # Title — same row as toggle, sticky="w" (no n/s) so the grid manager
        # centres it vertically inside the shared row → aligned with the icon.
        self._header_course_var = tk.StringVar(value=self._t("no_session_loaded"))
        self._header_course_lbl = tk.Label(
            top_bar, textvariable=self._header_course_var,
            bg=_card_bg, fg=_c0["text_fg"],
            font=("TkDefaultFont", 14, "bold"),
            anchor="w",
        )
        self._header_course_lbl.grid(row=0, column=1, sticky="w",
                                     padx=(0, 4), pady=4)

        # Status label — row 1, below the title; used for busy / error states.
        # The new-session hint is shown in the chat area instead (see
        # _session_mixin._on_new_session).
        self._session_status_var = tk.StringVar(value="")
        self._session_status_lbl = tk.Label(
            top_bar, textvariable=self._session_status_var,
            bg=_card_bg, fg=_c0.get("status_fg", "#6b7280"),
            font=("TkDefaultFont", 10),
            anchor="w",
        )
        self._session_status_lbl.grid(row=1, column=1, sticky="w",
                                      padx=(0, 4), pady=(0, 4))

        # Alias kept so _appearance_mixin theme loops still resolve.
        self._top_bar_info_area = top_bar

        # ── row 1 of _hist_inner: Scrollable rounded-bubble message list ────
        self._hist_frame = hist_frame = tk.Frame(self._hist_inner, bg=_card_bg)
        hist_frame.grid(row=1, column=0, sticky="nsew")
        hist_frame.rowconfigure(0, weight=1)
        hist_frame.columnconfigure(0, weight=1)

        # Viewport canvas — all bubbles scroll inside this canvas
        self._msg_canvas = tk.Canvas(
            hist_frame, bg=_card_bg, highlightthickness=0, bd=0,
        )
        self._msg_canvas.grid(row=0, column=0, sticky="nsew")

        self._chat_vsb = AutoHideScrollbar(
            hist_frame, orient="vertical",
            color=_c0["sb_color"], bg=_c0["sb_bg"],
        )
        self._msg_canvas.configure(yscrollcommand=self._chat_vsb.set)

        # Inner frame: one bubble widget per message, stacked vertically
        self._msg_frame = tk.Frame(self._msg_canvas, bg=_card_bg)
        self._msg_frame.columnconfigure(0, weight=1)
        self._msg_frame_win = self._msg_canvas.create_window(
            0, 0, anchor="nw", window=self._msg_frame,
        )
        self._msg_frame.bind(
            "<Configure>", lambda _e: self._on_msg_frame_configure())
        self._msg_canvas.bind(
            "<Configure>", lambda e: self._on_msg_canvas_configure(e))

        # Platform mousewheel scroll (canvas only — child bubbles get bound
        # individually in _append_chat via _bind_chat_scroll)
        import sys as _sys_plat
        if _sys_plat.platform == "darwin":
            self._msg_canvas.bind(
                "<MouseWheel>",
                lambda e: self._msg_canvas.yview_scroll(
                    int(-1 * e.delta), "units"))
        elif _sys_plat.platform.startswith("win"):
            self._msg_canvas.bind(
                "<MouseWheel>",
                lambda e: self._msg_canvas.yview_scroll(
                    int(-1 * (e.delta / 120)), "units"))
        else:
            self._msg_canvas.bind(
                "<Button-4>",
                lambda _e: self._msg_canvas.yview_scroll(-1, "units"))
            self._msg_canvas.bind(
                "<Button-5>",
                lambda _e: self._msg_canvas.yview_scroll(1, "units"))

        # Clicking the message area returns focus to the main window so the
        # search entry doesn't keep capturing keystrokes.
        self._msg_canvas.bind("<Button-1>", lambda _e: self.focus_set(), add="+")
        self._msg_frame.bind( "<Button-1>", lambda _e: self.focus_set(), add="+")

        # Refs used by _append_chat / _append_output_link / _show_thinking
        self._last_assistant_content: tk.Widget | None = None
        self._thinking_lbl: tk.Widget | None = None

        # ── row 2 of _hist_inner: Input block ────────────────────────────
        # Parented directly to _hist_inner — no separate outer canvas.
        # The chat area is flat (no bounding box); input block sits flush
        # at the bottom of the canvas.
        #
        # Internal layout:
        #   row 0 — quick-action chips  (always visible)
        #   row 1 — input text field    (always visible)
        #   row 2 — controls row        (Effort | spacer | [Sess Settings] | Send)
        self._input_max_lines = 5
        self._qa_chips: list          = []
        self._input_block_seps: list  = []   # unused; kept for compat
        self._input_block_bgs: list[tk.Widget] = []
        self._effort_flat_widgets: list[tk.Widget] = []

        # Session Settings hover state
        self._sess_settings_visible = False   # starts hidden
        self._input_hover_check_id: object = None

        self._input_block = tk.Frame(self._hist_inner, bg=_c0["input_bg"])
        self._input_block.grid(row=2, column=0, sticky="ew")
        self._input_block.columnconfigure(0, weight=1)

        # ── row 0: quick-action chips (always visible) ────────────────
        chips_row = tk.Frame(self._input_block, bg=_c0["input_bg"])
        chips_row.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 6))
        self._input_block_bgs.append(chips_row)
        self._qa_chips_row = chips_row   # kept for theme updates

        _qa_label = tk.Label(chips_row, text=self._t("quick_actions"),
                              bg=_c0["input_bg"],
                              fg=_c0.get("status_fg", "#9aa5be"),
                              font=("TkDefaultFont", 12))
        _qa_label.pack(side="left", padx=(0, 6))
        self._qa_chips.append(_qa_label)
        self._i18n_widgets.append((_qa_label, "text", "quick_actions"))

        for _qa_key, _qa_msg in _QUICK_ACTIONS:
            _chip = _RoundedChip(
                chips_row,
                text=self._t(_qa_key),
                chip_bg=_c0["qa_bg"],
                chip_fg=_c0["qa_fg"],
                parent_bg=_c0["input_bg"],
                font=("TkDefaultFont", 12),
                padx=9, pady=4,
                hover_bg=_c0.get("qa_bg_hover", _c0["qa_bg"]),
                command=lambda m=_qa_msg: self._send_message(m),
            )
            _chip.pack(side="left", padx=(0, 6))
            self._qa_chips.append(_chip)
            self._i18n_widgets.append((_chip, "text", _qa_key))

        # ── row 1: rounded input canvas + text widget ─────────────
        # A Canvas draws the rounded rectangle border; the Text widget sits
        # inside it via create_window.  The canvas height is kept in sync with
        # the text widget's required height by _sync_input_text_cv_height().
        _inner_bg = _c0.get("text_bg", "#ffffff")
        _border   = _c0.get("input_border", "#cdd4e8")
        _cv_pad   = 4   # gap between canvas edge and inner text window

        self._input_text_cv = tk.Canvas(
            self._input_block,
            bg=_c0["input_bg"],
            highlightthickness=0, bd=0,
            height=38,   # initial single-line height; updated dynamically
        )
        self._input_text_cv.grid(row=1, column=0, sticky="ew",
                                  padx=12, pady=(0, 6))
        self._input_text_cv.bind(
            "<Configure>", lambda _: self._redraw_input_text_cv())

        self._input_text = tk.Text(
            self._input_text_cv,
            height=1, wrap="word",
            font=("TkDefaultFont", 13),
            relief="flat", bd=0,
            highlightthickness=0,
            bg=_inner_bg,
            fg=_c0["input_fg"],
            insertbackground=_c0["input_fg"],
            padx=10, pady=8,
        )
        self._input_text_cv_win = self._input_text_cv.create_window(
            _cv_pad, _cv_pad, anchor="nw", window=self._input_text,
        )
        self._input_text.bind("<KeyRelease>", self._auto_resize_input)
        self._input_text.bind("<Return>",     self._on_return_key)
        # Sync canvas height whenever the text widget itself resizes
        self._input_text.bind(
            "<Configure>", lambda _: self._sync_input_text_cv_height())

        # Overlay scrollbar — floats inside the canvas when content overflows
        self._input_vsb = AutoHideScrollbar(
            self._input_text_cv, orient="vertical",
            color=_c0["sb_color"],
            bg=_inner_bg,
        )
        self._input_text.configure(yscrollcommand=self._input_vsb.set)

        # ── row 2: controls row ───────────────────────────────────────
        controls_row = tk.Frame(self._input_block, bg=_c0["input_bg"])
        controls_row.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 8))
        controls_row.columnconfigure(1, weight=1)
        self._input_block_bgs.append(controls_row)

        effort_left = tk.Frame(controls_row, bg=_c0["input_bg"])
        effort_left.grid(row=0, column=0, sticky="w")
        self._input_block_bgs.append(effort_left)

        _effort_lbl = tk.Label(
            effort_left, text=self._t("effort_label"),
            bg=_c0["input_bg"], fg=_c0.get("status_fg", "#6b7280"),
            font=("TkDefaultFont", 11),
        )
        _effort_lbl.pack(side="left", padx=(0, 4))
        self._effort_flat_widgets.append(_effort_lbl)
        self._i18n_widgets.append((_effort_lbl, "text", "effort_label"))

        # Single chip shows the current effort level; left-click opens a
        # popup menu to switch.  No always-visible radio clutter.
        self._effort_chip = _RoundedChip(
            effort_left,
            text=self._effort_chip_text(),
            chip_bg=_c0.get("qa_bg", "#edf0f8"),
            chip_fg=_c0["input_fg"],
            parent_bg=_c0["input_bg"],
            font=("TkDefaultFont", 11),
            padx=9, pady=4,
            hover_bg=_c0.get("qa_bg_hover", _c0.get("qa_bg", "#edf0f8")),
            outline=_c0.get("input_border", "#cdd4e8"),
            outline_width=1,
            command=self._show_effort_menu,
        )
        self._effort_chip.pack(side="left", padx=(0, 6))

        right_ctrls = tk.Frame(controls_row, bg=_c0["input_bg"])
        right_ctrls.grid(row=0, column=2, sticky="e")
        self._input_block_bgs.append(right_ctrls)

        # Session Settings — padx=14 ensures the full text is never clipped
        self._sess_settings_btn = _RoundedChip(
            right_ctrls,
            text=self._t("settings_btn"),
            chip_bg=_c0["input_bg"],
            chip_fg=_c0["input_fg"],
            parent_bg=_c0["input_bg"],
            font=("TkDefaultFont", 11),
            padx=14, pady=5,
            hover_bg=_c0.get("qa_bg", "#edf0f8"),
            outline=_c0.get("input_border", "#cdd4e8"),
            outline_width=1,
            command=self._open_settings,
        )
        self._sess_settings_btn.pack(side="left", padx=(0, 6))
        self._i18n_widgets.append((self._sess_settings_btn, "text", "settings_btn"))

        self._send_btn = _RoundedChip(
            right_ctrls,
            text=self._t("send"),
            chip_bg=_c0["btn_primary_bg"],
            chip_fg=_c0["btn_primary_fg"],
            parent_bg=_c0["input_bg"],
            font=("TkDefaultFont", 11, "bold"),
            padx=14, pady=5,
            hover_bg=_c0.get("btn_primary_hover", "#e8961a"),
            disabled_bg="#c8c8c8",
            disabled_fg="#888888",
            command=self._on_send,
        )
        self._send_btn.pack(side="left")
        self._i18n_widgets.append((self._send_btn, "text", "send"))

        # Cancel replaces Send while the agent is busy (not shown by default)
        self._cancel_btn = _RoundedChip(
            right_ctrls,
            text=self._t("cancel"),
            chip_bg=_c0.get("btn_cancel_bg", "#e53e3e"),
            chip_fg=_c0.get("btn_cancel_fg", "#ffffff"),
            parent_bg=_c0["input_bg"],
            font=("TkDefaultFont", 11, "bold"),
            padx=14, pady=5,
            hover_bg=_c0.get("btn_cancel_hover", "#c53030"),
            command=self._on_cancel,
        )
        self._i18n_widgets.append((self._cancel_btn, "text", "cancel"))
        # Send is visible by default; Cancel swaps in when busy (pack_forget / pack)

        # Session Settings button is always visible inside the input block.
        self._show_sess_settings()

        # ── Placeholder (shown when no session is active) ─────────────────
        # Grids at row=0 (the only row in `right`) so it fills the full pane.
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
    # Effort level chip helpers
    # ------------------------------------------------------------------

    def _effort_chip_text(self) -> str:
        """Return the effort chip label — current level display name + caret."""
        level = self._effort_var.get() if hasattr(self, "_effort_var") else "medium"
        return f"{self._t(level)} ▾"

    def _show_effort_menu(self) -> None:
        """Show a popup menu below the effort chip to switch the level."""
        menu = tk.Menu(self.winfo_toplevel(), tearoff=0)
        for _lvl in ("low", "medium", "high"):
            menu.add_command(
                label=self._t(_lvl),
                command=lambda l=_lvl: self._select_effort(l),
            )
        try:
            x = self._effort_chip.winfo_rootx()
            y = self._effort_chip.winfo_rooty() + self._effort_chip.winfo_height()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _select_effort(self, level: str) -> None:
        """Set the effort level and refresh the chip text."""
        self._effort_var.set(level)
        try:
            self._effort_chip.set_text(self._effort_chip_text())
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Sidebar toggle
    # ------------------------------------------------------------------

    def _toggle_sidebar(self) -> None:
        """Show or hide the session list panel.

        When hiding, the current sash position is saved so the sidebar can be
        restored to its previous width when shown again.  Because
        ``tk.PanedWindow.add()`` always appends, we re-insert the sidebar at
        position 0 by temporarily removing the chat pane, adding the sidebar,
        then re-adding the chat pane.
        """
        if self._sidebar_visible:
            # Snapshot sash position before removing the pane
            try:
                self._saved_sash_pos = self._paned.sash_coord(0)[0]
            except Exception:
                self._saved_sash_pos = _SESSION_LIST_WIDTH
            self._paned.forget(self._sidebar_frame)
            self._sidebar_visible = False
            self._toggle_sidebar_btn.set_sidebar_visible(False)
        else:
            # PanedWindow.add() appends, so remove chat first, then add
            # sidebar (→ position 0), then re-add chat (→ position 1).
            self._paned.forget(self._chat_frame)
            self._paned.add(
                self._sidebar_frame,
                minsize=160,
                width=self._saved_sash_pos,
                stretch="never",
            )
            self._paned.add(self._chat_frame, minsize=500, stretch="always")
            self._sidebar_visible = True
            self._toggle_sidebar_btn.set_sidebar_visible(True)

    # ------------------------------------------------------------------
    # Rounded-corner list canvas
    # ------------------------------------------------------------------

    def _redraw_list_canvas(self) -> None:
        """Repaint the rounded-rectangle background on the session list canvas.

        Called on every ``<Configure>`` event of ``_list_canvas`` and after
        each theme change.  The canvas background is set to the sidebar
        colour; a filled rounded-rect polygon in the list-background colour
        sits on top, and the inner Frame (which has the same list-background
        colour) sits on top of that — so the rectangular corners of the Frame
        are invisible and only the canvas corners (showing the sidebar bg)
        reveal the rounded shape.
        """
        if not hasattr(self, "_list_canvas"):
            return
        w = self._list_canvas.winfo_width()
        h = self._list_canvas.winfo_height()
        if w <= 1 or h <= 1:
            return

        _mode = self._color_mode_var.get() if hasattr(self, "_color_mode_var") else "light"
        c = _THEME_COLORS.get(_mode, _THEME_COLORS["light"])
        fill  = c["lb_bg"]
        bg    = c["window_bg"]   # sidebar sits on window background

        self._list_canvas.configure(bg=bg)
        self._list_inner.configure(bg=fill)

        # Draw (or redraw) the rounded-rectangle with a subtle border outline
        self._list_canvas.delete("rrect")
        r   = 12    # corner radius in px
        pad = 3     # gap between canvas edge and rounded rect
        border_col = c.get("input_border", "#cdd4e8")
        draw_rounded_rect(
            self._list_canvas,
            pad, pad, w - pad, h - pad,
            r=r,
            fill=fill,
            outline=border_col,
            width=1,
            tags="rrect",
        )
        self._list_canvas.tag_lower("rrect")

        # Keep inner Frame sized to fill the rounded-rect area
        inner_pad = pad + 2
        self._list_canvas.itemconfigure(
            self._list_canvas_id,
            width=max(1, w - 2 * inner_pad),
            height=max(1, h - 2 * inner_pad),
        )
        self._list_canvas.coords(self._list_canvas_id, inner_pad, inner_pad)

    # ------------------------------------------------------------------
    # Compound input block canvas
    # ------------------------------------------------------------------

    def _redraw_input_block_canvas(self) -> None:
        """Update colours of the input block widgets after a theme change.

        The input block is now parented directly inside ``_hist_inner`` (no
        separate outer canvas), so this method only needs to repaint chip
        colours and background frames — no polygon drawing required.
        """
        if not hasattr(self, "_input_block"):
            return

        _mode = self._color_mode_var.get() if hasattr(self, "_color_mode_var") else "light"
        c = _THEME_COLORS.get(_mode, _THEME_COLORS["light"])

        try:
            self._input_block.configure(bg=c["input_bg"])
        except Exception:
            pass

        # 1. Update quick-action chip colours
        qa_bg      = c.get("qa_bg",       c["input_bg"])
        qa_fg      = c.get("qa_fg",       c.get("text_fg", "#1a2744"))
        qa_hov     = c.get("qa_bg_hover", qa_bg)
        st_fg      = c.get("status_fg",   "#9aa5be")
        _inp_bg_c  = c["input_bg"]
        for i, chip in enumerate(self._qa_chips):
            try:
                if i == 0:
                    chip.configure(bg=_inp_bg_c, fg=st_fg)
                else:
                    chip.update_style(
                        chip_bg=qa_bg, chip_fg=qa_fg,
                        hover_bg=qa_hov, parent_bg=_inp_bg_c,
                    )
            except Exception:
                pass

        # 2. Update background frames
        for bg_widget in self._input_block_bgs:
            try:
                bg_widget.configure(bg=c["input_bg"])
            except Exception:
                pass

        # 3. Update the input text widget colours
        try:
            self._redraw_input_text_cv()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Rounded input text-field canvas (nested inside the input card)
    # ------------------------------------------------------------------

    def _redraw_input_text_cv(self) -> None:
        """Repaint the rounded border around the input text widget.

        Called on every ``<Configure>`` of ``_input_text_cv`` and after each
        theme change.  Draws a filled rounded rect (r=10) in ``text_bg`` with
        a ``input_border`` outline, then sizes the inner text-window to fill
        the padded interior.
        """
        if not hasattr(self, "_input_text_cv"):
            return
        w = self._input_text_cv.winfo_width()
        h = self._input_text_cv.winfo_height()
        if w <= 1 or h <= 1:
            return
        _mode = self._color_mode_var.get() if hasattr(self, "_color_mode_var") else "light"
        c = _THEME_COLORS.get(_mode, _THEME_COLORS["light"])

        inner_bg = c.get("text_bg", "#ffffff")
        border   = c.get("input_border", "#cdd4e8")
        _cv_pad  = 4

        self._input_text_cv.configure(bg=c["input_bg"])
        self._input_text_cv.delete("itf")
        # Inset 1 px so the 1-px outline is never clipped at the canvas edge.
        draw_rounded_rect(
            self._input_text_cv, 1, 1, w - 1, h - 1, r=10,
            fill=inner_bg, outline=border, width=1,
            tags="itf",
        )
        # Size the text window to fill inside the rounded rect
        self._input_text_cv.itemconfigure(
            self._input_text_cv_win,
            width=max(1, w - 2 * _cv_pad),
            height=max(1, h - 2 * _cv_pad),
        )
        self._input_text_cv.tag_raise(self._input_text_cv_win)

        # Keep text widget colours in sync
        try:
            self._input_text.configure(
                bg=inner_bg, fg=c["input_fg"],
                insertbackground=c["input_fg"],
            )
        except Exception:
            pass
        try:
            self._input_vsb.update_style(c["sb_color"], inner_bg)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Rounded chat history canvas
    # ------------------------------------------------------------------

    def _redraw_hist_canvas(self) -> None:
        """Repaint the chat card and size _hist_inner to fit inside it.

        The card is flush with the right, top, and bottom window edges.
        Only its LEFT side is inset, with rounded top-left and bottom-left
        corners — these curves are the only visual divider between the
        sidebar and the chat area.  The PanedWindow sash (invisible but
        present) sits at this left boundary and remains draggable.
        """
        if not hasattr(self, "_hist_canvas"):
            return
        w = self._hist_canvas.winfo_width()
        h = self._hist_canvas.winfo_height()
        if w <= 1 or h <= 1:
            return
        _mode = self._color_mode_var.get() if hasattr(self, "_color_mode_var") else "light"
        c = _THEME_COLORS.get(_mode, _THEME_COLORS["light"])
        card_bg = c["text_bg"]
        wbg     = c["window_bg"]

        # Card geometry: left edge at x=0 (flush with canvas/sash boundary),
        # right/top/bottom flush with canvas edges (no margin on those sides).
        r = 18   # corner radius for the left-side curves

        self._hist_canvas.configure(bg=wbg)
        self._hist_canvas.delete("hc")
        draw_left_rounded_rect(
            self._hist_canvas,
            0, 0, w, h,
            r=r,
            fill=card_bg,
            outline="",
            tags="hc",
        )

        # _hist_inner must not reach the rounded-corner area on the left.
        # The deepest the left arc intrudes rightward is at its midpoint
        # (y = r), where x_boundary = r*(1 - cos(45°)) ≈ 0.293*r.
        # Using inner_x = r + 4 keeps the inner frame safely inside.
        inner_x = r + 4
        inner_y = 4
        inner_w = max(1, w - inner_x - 4)
        inner_h = max(1, h - inner_y - 4)
        self._hist_canvas.itemconfigure(
            self._hist_canvas_win, width=inner_w, height=inner_h,
        )
        self._hist_canvas.coords(self._hist_canvas_win, inner_x, inner_y)
        self._hist_inner.configure(bg=card_bg)
        self._hist_canvas.tag_raise(self._hist_canvas_win)

        # Update message bubble canvas and inner frame backgrounds
        try:
            self._msg_canvas.configure(bg=c["text_bg"])
            self._msg_frame.configure(bg=c["text_bg"])
        except Exception:
            pass

        # Update the separator between top bar and chat
        try:
            self._chat_separator.configure(bg=c.get("paned_bg", "#c8d0e0"))
        except Exception:
            pass

        # Update the divider between chat and input
        try:
            self._card_sep.configure(bg=c.get("input_border", "#cdd4e8"))
        except Exception:
            pass

        # Update input block colours
        try:
            self._redraw_input_block_canvas()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Auto-expand input text
    # ------------------------------------------------------------------

    def _auto_resize_input(self, event=None) -> None:
        """Grow/shrink the input Text height to fit content (max 5 lines).

        Growth always pushes the card upward (the chat history shrinks from
        the bottom) because the input block sits in a fixed-weight grid row
        at the bottom of the chat pane.  Once the 5-line limit is reached
        the text widget scrolls internally — no further card expansion.

        Uses ``text.count("1.0", "end-1c", "displaylines")`` rather than a
        ``dlineinfo`` loop so the line count is accurate even when the text
        has scrolled beyond the visible viewport (dlineinfo returns None for
        off-screen lines and would collapse the widget to height=1).
        """
        try:
            self._input_text.update_idletasks()   # flush wrapping before counting
            n = self._input_text.count("1.0", "end-1c", "displaylines")
            if n is None:
                n = 0
            # count() can return a tuple when multiple options are passed;
            # unwrap it when it does.
            if isinstance(n, tuple):
                n = n[0] if n else 0
            new_h = max(1, min(self._input_max_lines, n))
            if int(str(self._input_text.cget("height"))) != new_h:
                self._input_text.configure(height=new_h)
                self.after(5, self._sync_input_text_cv_height)
        except Exception:
            pass

    def _sync_input_text_cv_height(self) -> None:
        """Resize the input canvas to match the text widget's current height.

        Called after ``_auto_resize_input`` changes the Text height option and
        also via the Text widget's ``<Configure>`` binding so the rounded-rect
        canvas always wraps the content snugly.
        """
        if not hasattr(self, "_input_text_cv") or not hasattr(self, "_input_text"):
            return
        try:
            req_h = self._input_text.winfo_reqheight()
            if req_h < 2:
                return
            _cv_pad = 4
            new_cv_h = req_h + 2 * _cv_pad
            cur_cv_h = self._input_text_cv.winfo_height()
            if abs(cur_cv_h - new_cv_h) > 1:
                self._input_text_cv.configure(height=new_cv_h)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Chat pane show / hide
    # ------------------------------------------------------------------

    def _set_chat_active(self, active: bool) -> None:
        """Show the full chat UI (active=True) or a blank placeholder (active=False).

        The top bar, separator, chat history, and input block all live inside
        ``_hist_inner`` which is embedded in ``_hist_canvas`` — so toggling the
        canvas alone is sufficient.  The placeholder fills the single row=0 cell.
        """
        if active:
            self._placeholder_frame.grid_remove()
            self._hist_canvas.grid()   # restores original grid options
        else:
            self._hist_canvas.grid_remove()
            self._placeholder_frame.grid(row=0, column=0, sticky="nsew")

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
        if busy:
            self._thinking_active = True
            self._cancel_event.clear()
            # Swap: hide Send, show Cancel in its place
            self._send_btn.pack_forget()
            self._cancel_btn.pack(side="left")
            if label:
                self._show_thinking(label)
        else:
            # Kill indicator BEFORE swapping buttons so no flash
            self._thinking_active = False
            self._hide_thinking()
            self._cancel_btn.pack_forget()
            self._send_btn.pack(side="left")

    # ------------------------------------------------------------------
    # Thinking indicator (lives in the chat window)
    # ------------------------------------------------------------------

    def _show_thinking(self, label: str) -> None:
        """Show (or replace) a progress indicator at the bottom of the chat area.

        Uses a plain ``tk.Label`` appended to ``_msg_frame``.  Stale callbacks
        are silently dropped via ``_thinking_active``.
        """
        if not getattr(self, "_thinking_active", False):
            return   # _set_busy(False) already ran — discard stale callback
        if not hasattr(self, "_msg_frame"):
            return
        try:
            self._hide_thinking()   # remove any previous indicator first
            _mode = self._color_mode_var.get() if hasattr(self, "_color_mode_var") else "light"
            c = _THEME_COLORS.get(_mode, _THEME_COLORS["light"])
            lbl = tk.Label(
                self._msg_frame,
                text=label,
                bg=c.get("text_bg", "#ffffff"),
                fg=c.get("status_fg", "#9aa5be"),
                font=("TkDefaultFont", 11, "italic"),
                anchor="w", padx=20, pady=6,
            )
            lbl.pack(fill="x", pady=(0, 4))
            self._thinking_lbl = lbl
            self._scroll_chat_to_bottom()
        except Exception:
            pass

    def _hide_thinking(self) -> None:
        """Remove the thinking indicator label if it exists."""
        lbl = getattr(self, "_thinking_lbl", None)
        if lbl is not None:
            try:
                lbl.destroy()
            except Exception:
                pass
            self._thinking_lbl = None


    # ------------------------------------------------------------------
    # Scrollable message-bubble canvas helpers
    # ------------------------------------------------------------------

    def _on_msg_frame_configure(self) -> None:
        """Update the canvas scrollregion when the inner message frame resizes."""
        if not hasattr(self, "_msg_canvas"):
            return
        try:
            self._msg_canvas.configure(
                scrollregion=self._msg_canvas.bbox("all"))
        except Exception:
            pass

    def _on_msg_canvas_configure(self, event) -> None:
        """Keep inner message frame width in sync with canvas viewport width."""
        if not hasattr(self, "_msg_frame_win"):
            return
        try:
            self._msg_canvas.itemconfigure(
                self._msg_frame_win, width=event.width)
        except Exception:
            pass

    def _scroll_chat_to_bottom(self) -> None:
        """Scroll the message bubble canvas to reveal the latest message."""
        if not hasattr(self, "_msg_canvas"):
            return
        try:
            self._msg_canvas.update_idletasks()
            self._msg_canvas.yview_moveto(1.0)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Search bar canvas
    # ------------------------------------------------------------------

    def _redraw_search_cv(self) -> None:
        """Repaint the rounded border around the sidebar search entry.

        Called on every ``<Configure>`` of ``_search_cv`` and after each
        theme/font change.  Draws a filled rounded rect (r=8) with an
        ``input_border`` outline, places a 🔍 icon as a canvas text item,
        and resizes the embedded Entry to fill the right portion.
        """
        if not hasattr(self, "_search_cv"):
            return
        cv = self._search_cv
        w  = cv.winfo_width()
        h  = cv.winfo_height()
        if w <= 1 or h <= 1:
            return
        _mode = self._color_mode_var.get() if hasattr(self, "_color_mode_var") else "light"
        c    = _THEME_COLORS.get(_mode, _THEME_COLORS["light"])
        _sbg = c["sidebar_bg"]
        _ibg = c.get("input_bg", c.get("lb_bg", "#e8ecf5"))
        _brd = c.get("input_border", "#cdd4e8")
        _fg  = c.get("lb_fg", "#1a2744")

        cv.configure(bg=_sbg)
        cv.delete("sc")
        cv.delete("sc_icon")
        draw_rounded_rect(cv, 1, 1, w - 1, h - 1, r=8,
                          fill=_ibg, outline=_brd, width=1, tags="sc")
        cv.create_text(14, h // 2, text="🔍",
                       font=("TkDefaultFont", 10),
                       fill=_fg, anchor="center", tags="sc_icon")
        cv.itemconfigure(self._search_cv_win,
                         width=max(1, w - 32), height=max(1, h - 8))
        cv.coords(self._search_cv_win, 28, 4)
        cv.tag_raise(self._search_cv_win)
        try:
            self._search_entry.configure(bg=_ibg, fg=_fg, insertbackground=_fg)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Input-block hover — Session Settings reveal
    # ------------------------------------------------------------------

    # (hover-reveal removed — Session Settings is always visible)

    def _show_sess_settings(self) -> None:
        """Restore Session Settings chip to its proper visible colours."""
        self._sess_settings_visible = True
        _mode = self._color_mode_var.get() if hasattr(self, "_color_mode_var") else "light"
        c     = _THEME_COLORS.get(_mode, _THEME_COLORS["light"])
        try:
            self._sess_settings_btn.update_style(
                chip_bg=c["input_bg"],
                chip_fg=c["input_fg"],
                hover_bg=c.get("qa_bg", c["input_bg"]),
                parent_bg=c["input_bg"],
                outline=c.get("input_border", "#cdd4e8"),
                outline_width=1,
            )
        except Exception:
            pass

    def _hide_sess_settings(self) -> None:
        """Make Session Settings chip transparent (invisible against input bg)."""
        self._sess_settings_visible = False
        _mode = self._color_mode_var.get() if hasattr(self, "_color_mode_var") else "light"
        c     = _THEME_COLORS.get(_mode, _THEME_COLORS["light"])
        _ibg  = c["input_bg"]
        try:
            self._sess_settings_btn.update_style(
                chip_bg=_ibg,
                chip_fg=_ibg,
                hover_bg=_ibg,
                parent_bg=_ibg,
                outline=_ibg,
                outline_width=0,
            )
        except Exception:
            pass

    def _bind_chat_scroll(self, widget: tk.Widget) -> None:
        """Bind mousewheel events on *widget* to scroll the message canvas."""
        import sys as _sys_bs
        if not hasattr(self, "_msg_canvas"):
            return
        if _sys_bs.platform == "darwin":
            widget.bind(
                "<MouseWheel>",
                lambda e: self._msg_canvas.yview_scroll(
                    int(-1 * e.delta), "units"),
                add="+",
            )
        elif _sys_bs.platform.startswith("win"):
            widget.bind(
                "<MouseWheel>",
                lambda e: self._msg_canvas.yview_scroll(
                    int(-1 * (e.delta / 120)), "units"),
                add="+",
            )
        else:
            widget.bind(
                "<Button-4>",
                lambda _e: self._msg_canvas.yview_scroll(-1, "units"),
                add="+",
            )
            widget.bind(
                "<Button-5>",
                lambda _e: self._msg_canvas.yview_scroll(1, "units"),
                add="+",
            )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    from dotenv import load_dotenv
    from uacragent.infra.persistence import configure_hf_cache, get_app_data_dir

    # Load .env from the app workspace folder (~/.uacragent/.env) so the app
    # picks up API keys regardless of which directory it was launched from.
    # A .env in the current working directory is also honoured afterwards as a
    # lower-priority fallback (useful during development).
    _app_env = get_app_data_dir() / ".env"
    if _app_env.exists():
        load_dotenv(_app_env)
    load_dotenv()   # cwd fallback; won't override keys already loaded above

    # Redirect HuggingFace model downloads into the app data folder so all
    # agent data lives in one place.  Must run before any HF import.
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
