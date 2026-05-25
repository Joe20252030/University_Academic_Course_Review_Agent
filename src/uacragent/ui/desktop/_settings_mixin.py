"""Session Settings dialog methods."""
from __future__ import annotations

import os
import re
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from uacragent.domain.providers import (
    PROVIDER_IDS, get_provider, env_var_for, models_for,
)
from uacragent.domain.types import DocumentType, ExamFormat, ExamType, ExportFormat
from uacragent.infra.persistence import get_app_data_dir
from uacragent.infra.workspace import workspace_paths

from ._ui_constants import (
    _PAD, _SUPPORTED_FILETYPES, _STRINGS, _THEME_COLORS, _FONT_SIZE_VALUES,
    _open_file_in_os, _open_folder_in_os,
)


class SettingsMixin:
    """Mixin: session settings dialog — open, apply, and all helper methods."""

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

    def _center_on_main(self, win: tk.Toplevel) -> None:
        """Position *win* at the centre of the main application window.

        Must be called after the dialog's widgets are built and packed so
        that ``winfo_reqwidth`` / ``winfo_reqheight`` return real sizes.
        We use ``after_idle`` to let tkinter finish its layout pass first.

        Note: screen coordinates are intentionally *not* clamped to ≥ 0.
        On multi-monitor setups, monitors to the left or above the primary
        display have negative x/y coordinates, and clamping to 0 would
        incorrectly snap the dialog to the primary monitor instead.
        """
        def _do_center() -> None:
            try:
                win.update_idletasks()          # flush pending geometry requests
                # Dialog's natural size (may be 0×0 before layout; fall back)
                dw = win.winfo_reqwidth()  or win.winfo_width()
                dh = win.winfo_reqheight() or win.winfo_height()
                # Main window position and size — winfo_rootx/y gives absolute
                # screen coords, which are correct across all monitors.
                mw = self.winfo_width()
                mh = self.winfo_height()
                mx = self.winfo_rootx()
                my = self.winfo_rooty()
                # Centre the dialog over the main window
                x = mx + (mw - dw) // 2
                y = my + (mh - dh) // 2
                win.geometry(f"+{x}+{y}")
            except tk.TclError:
                pass  # window already destroyed

        win.after_idle(_do_center)

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

        # Rate tier — ground truth is RATE_TIER env var (written by _inject_api_keys).
        from uacragent.domain.rate_tiers import get_rate_tier
        _committed_tier = get_rate_tier(os.environ.get("RATE_TIER", "free"))
        self._rate_tier_disp_var.set(_committed_tier.display_name)

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
        win.title(self._t("settings_dialog_title"))
        win.minsize(560, 600)
        win.resizable(True, True)
        self._settings_win = win

        # ── Fixed banner (always visible, above the scroll area) ──────
        _note_sz = max(self._font_size() - 1, 10)  # notice font: 1pt below body, min 10
        banner = tk.Frame(win, background="#fff8e1", padx=10, pady=6)
        banner.pack(side="top", fill="x")
        tk.Label(
            banner,
            text=self._t("settings_banner"),
            background="#fff8e1",
            foreground="#5d4037",
            font=("TkDefaultFont", _note_sz),
            anchor="w",
        ).pack(side="left")

        # ── Fixed bottom bar (always visible, below the scroll area) ─
        bottom_bar = ttk.Frame(win, padding=(10, 6))
        bottom_bar.pack(side="bottom", fill="x")
        ttk.Separator(win, orient="horizontal").pack(side="bottom", fill="x")

        self._settings_status_var = tk.StringVar(value="")
        ttk.Label(bottom_bar, textvariable=self._settings_status_var,
                  foreground="gray", font=("TkDefaultFont", _note_sz),
                  wraplength=440
                  ).pack(side="left", fill="x", expand=True)

        _action_frame = ttk.Frame(bottom_bar)
        _action_frame.pack(side="right")
        ttk.Button(_action_frame, text=self._t("settings_apply_btn"),
                   command=self._on_apply_settings
                   ).pack(side="left", padx=(0, 8))
        ttk.Button(_action_frame, text=self._t("settings_close_btn"),
                   command=win.destroy
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
        # widget-level bindings automatically.

        inner.columnconfigure(0, weight=1)
        row = 0

        # ── Model Selection ───────────────────────────────────────────
        mf = ttk.LabelFrame(inner, text=self._t("settings_model_section"), padding=_PAD)
        mf.grid(row=row, column=0, sticky="ew", pady=(0, _PAD))
        mf.columnconfigure(1, weight=1)
        row += 1

        ttk.Label(mf, text=self._t("settings_provider_label")).grid(
            row=0, column=0, sticky="w", padx=(0, 8))
        provider_cb = ttk.Combobox(
            mf, textvariable=self._llm_provider_var,
            values=["gemini", "openai", "deepseek"],
            state="readonly", width=12)
        provider_cb.grid(row=0, column=1, sticky="w")
        provider_cb.bind("<<ComboboxSelected>>", self._on_provider_changed)

        ttk.Label(mf, text=self._t("settings_model_label")).grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
        self._model_cb = ttk.Combobox(
            mf, textvariable=self._llm_model_var, width=22)
        self._model_cb.grid(row=1, column=1, sticky="w", pady=(6, 0))
        self._update_model_list()   # populate for current provider

        # ── Request Frequency ─────────────────────────────────────────
        rf = ttk.LabelFrame(
            inner, text=self._t("settings_rate_section"), padding=_PAD)
        rf.grid(row=row, column=0, sticky="ew", pady=(0, _PAD))
        rf.columnconfigure(1, weight=1)
        row += 1

        ttk.Label(rf, text=self._t("settings_rate_tier_label")).grid(
            row=0, column=0, sticky="w", padx=(0, 8))

        from uacragent.domain.rate_tiers import (
            RATE_TIER_BY_DISPLAY, display_names, get_rate_tier)
        _rate_cb = ttk.Combobox(
            rf, textvariable=self._rate_tier_disp_var,
            values=display_names(),
            state="readonly", width=14)
        _rate_cb.grid(row=0, column=1, sticky="w")

        # Dynamic hint label — updated immediately when the combobox changes.
        self._rate_hint_var = tk.StringVar()
        _rate_hint_lbl = ttk.Label(
            rf, textvariable=self._rate_hint_var,
            foreground="gray",
            font=("TkDefaultFont", max(self._font_size() - 1, 10)),
            wraplength=460,
        )
        _rate_hint_lbl.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        def _update_rate_hint(*_: object) -> None:
            disp = self._rate_tier_disp_var.get()
            tier_id = RATE_TIER_BY_DISPLAY.get(disp, "free")
            tier    = get_rate_tier(tier_id)
            self._rate_hint_var.set(self._t(tier.hint_i18n_key))
            # Refresh the suggestion label whenever the tier selection changes.
            self._update_rate_suggestion()

        _rate_cb.bind("<<ComboboxSelected>>", _update_rate_hint)
        _update_rate_hint()   # populate immediately for the current selection

        # Suggestion label — blue info tone; only visible when current ≠ suggested.
        self._rate_suggestion_var = tk.StringVar()
        ttk.Label(
            rf, textvariable=self._rate_suggestion_var,
            foreground="#1565c0",
            font=("TkDefaultFont", max(self._font_size() - 1, 10)),
            wraplength=460,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 0))

        # ── API Key (single row, changes with provider) ───────────────
        akf = ttk.LabelFrame(inner, text=self._t("settings_api_key_section"), padding=_PAD)
        akf.grid(row=row, column=0, sticky="ew", pady=(0, _PAD))
        akf.columnconfigure(1, weight=1)
        row += 1

        self._api_key_label_var = tk.StringVar(value=self._t("api_key_google"))
        ttk.Label(akf, textvariable=self._api_key_label_var).grid(
            row=0, column=0, sticky="w", padx=(0, 8))

        # Single entry — textvariable is swapped by _update_api_key_row()
        self._active_key_entry = ttk.Entry(akf, show="*")
        self._active_key_entry.grid(row=0, column=1, sticky="ew", padx=(0, 4))

        self._api_key_show_btn = ttk.Button(
            akf, text=self._t("settings_show_key"), width=5,
            command=lambda: self._toggle_key_entry(
                self._active_key_entry, self._api_key_show_btn))
        self._api_key_show_btn.grid(row=0, column=2)

        self._api_key_hint_var = tk.StringVar()
        self._api_key_hint_lbl = ttk.Label(
            akf, textvariable=self._api_key_hint_var,
            font=("TkDefaultFont", _note_sz))
        self._api_key_hint_lbl.grid(row=0, column=3, padx=(6, 0))

        # Wire entry to current provider's var and update hint
        self._update_api_key_row()

        # ── API key scope notice ───────────────────────────────────────────
        note_frame = tk.Frame(akf, background="#e8f4fd",
                              highlightbackground="#90caf9", highlightthickness=1,
                              padx=8, pady=5)
        note_frame.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        tk.Label(
            note_frame,
            text=self._t("settings_api_key_note"),
            background="#e8f4fd", foreground="#0d47a1",
            font=("TkDefaultFont", _note_sz), anchor="w", justify="left", wraplength=460,
        ).pack(fill="x")

        # ── Embedding ─────────────────────────────────────────────────────
        embf = ttk.LabelFrame(inner, text=self._t("settings_embedding_section"), padding=_PAD)
        embf.grid(row=row, column=0, sticky="ew", pady=(0, _PAD))
        embf.columnconfigure(1, weight=1)
        row += 1

        ttk.Label(embf, text=self._t("settings_provider_label")).grid(
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
        inf = ttk.LabelFrame(inner, text=self._t("settings_course_section"), padding=_PAD)
        inf.grid(row=row, column=0, sticky="ew", pady=(0, _PAD))
        inf.columnconfigure(1, weight=1)
        row += 1

        fields = [
            (self._t("settings_course_name_field"), "red", self._course_name_var),
            (self._t("settings_university_field"),  None,  self._university_var),
            (self._t("settings_major_field"),        None,  self._major_var),
            (self._t("settings_course_code_field"), None,  self._course_code_var),
            (self._t("settings_professor_field"),   None,  self._professor_var),
            (self._t("settings_semester_field"),    None,  self._semester_var),
        ]
        for fi, (lbl, fg, var) in enumerate(fields):
            # Only set foreground when an explicit override is needed (e.g. red
            # for required fields). Omitting it for regular labels lets the ttk
            # style propagate correctly, including in dark mode.
            lbl_kw = {"foreground": fg} if fg else {}
            ttk.Label(inf, text=lbl + ":", **lbl_kw).grid(
                row=fi, column=0, sticky="w", padx=(0, 6), pady=(3, 0))
            e = ttk.Entry(inf, textvariable=var)
            e.grid(row=fi, column=1, sticky="ew", pady=(3, 0))
            if lbl == self._t("settings_course_name_field"):
                self._course_name_entry = e

        # ── Exam Options ──────────────────────────────────────────────
        ef = ttk.LabelFrame(inner, text=self._t("settings_exam_section"), padding=_PAD)
        ef.grid(row=row, column=0, sticky="ew", pady=(0, _PAD))
        ef.columnconfigure(1, weight=1)
        row += 1

        ttk.Label(ef, text=self._t("settings_exam_type_label")).grid(
            row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Combobox(ef, textvariable=self._exam_type_var,
                     values=[e.value for e in ExamType],
                     state="readonly", width=14
                     ).grid(row=0, column=1, sticky="w")

        ttk.Label(ef, text=self._t("settings_exam_format_label")).grid(
            row=1, column=0, sticky="w", padx=(0, 6), pady=(4, 0))
        ttk.Combobox(ef, textvariable=self._exam_format_var,
                     values=[e.value for e in ExamFormat],
                     state="readonly", width=14
                     ).grid(row=1, column=1, sticky="w", pady=(4, 0))

        ttk.Label(ef, text=self._t("settings_exam_duration_label")).grid(
            row=2, column=0, sticky="w", padx=(0, 6), pady=(4, 0))
        ttk.Entry(ef, textvariable=self._exam_duration_var).grid(
            row=2, column=1, sticky="ew", pady=(4, 0))

        ttk.Label(ef, text=self._t("settings_exam_info_label")).grid(
            row=3, column=0, sticky="w", padx=(0, 6), pady=(4, 0))
        ei_row = ttk.Frame(ef)
        ei_row.grid(row=3, column=1, sticky="ew", pady=(4, 0))
        ei_row.columnconfigure(0, weight=1)
        self._exam_info_path_label = ttk.Label(
            ei_row, textvariable=self._exam_info_path_var,
            foreground="gray", anchor="w", text="No file selected")
        self._exam_info_path_label.grid(row=0, column=0, sticky="ew")
        ttk.Button(ei_row, text=self._t("settings_browse_btn"), width=8,
                   command=self._on_pick_exam_info
                   ).grid(row=0, column=1, padx=(4, 0))
        ttk.Button(ei_row, text=self._t("settings_clear_btn"), width=6,
                   command=self._on_clear_exam_info
                   ).grid(row=0, column=2, padx=(4, 0))

        # ── Workspace & Export ────────────────────────────────────────
        wf = ttk.LabelFrame(inner, text=self._t("settings_workspace_section"), padding=_PAD)
        wf.grid(row=row, column=0, sticky="ew", pady=(0, _PAD))
        wf.columnconfigure(1, weight=1)
        row += 1

        ttk.Label(wf, text=self._t("settings_workspace_label")).grid(
            row=0, column=0, sticky="w", padx=(0, 6))
        ws_row = ttk.Frame(wf)
        ws_row.grid(row=0, column=1, sticky="ew")
        ws_row.columnconfigure(0, weight=1)
        if self._workspace_committed:
            # Locked: show the path as a read-only label + Open button
            path_text = self._workspace_var.get() or str(get_app_data_dir())
            ttk.Label(ws_row, text=path_text, foreground="#1a56a5",
                      anchor="w").grid(row=0, column=0, sticky="ew")
            ttk.Button(ws_row, text=self._t("settings_open_btn"), width=6,
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
            ttk.Button(ws_row, text=self._t("settings_browse_btn"), width=9,
                       command=self._on_pick_workspace
                       ).grid(row=0, column=1, padx=(4, 0))
            ttk.Button(ws_row, text=self._t("settings_reset_btn"), width=6,
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
            text=self._t("settings_deletion_warning_title"),
            background="#fff3e0", foreground="#bf360c",
            font=("TkDefaultFont", _note_sz, "bold"),
            anchor="w",
        ).pack(side="top", fill="x")
        tk.Label(
            warn_frame,
            text=self._t("settings_deletion_warning_body"),
            background="#fff3e0", foreground="#4e342e",
            font=("TkDefaultFont", _note_sz),
            anchor="w", justify="left", wraplength=460,
        ).pack(side="top", fill="x")

        ttk.Label(wf, text=self._t("settings_export_format_label")).grid(
            row=2, column=0, sticky="w", padx=(0, 6), pady=(6, 0))
        ttk.Combobox(wf, textvariable=self._export_format_var,
                     values=[e.value for e in ExportFormat],
                     state="readonly", width=12
                     ).grid(row=2, column=1, sticky="w", pady=(6, 0))

        ttk.Label(wf, text=self._t("settings_extra_instructions_label")).grid(
            row=3, column=0, sticky="nw", padx=(0, 6), pady=(6, 0))
        self._extra_text = tk.Text(wf, height=3, wrap="word")
        self._extra_text.grid(row=3, column=1, sticky="ew", pady=(6, 0))
        self._extra_text.insert("1.0", self._extra_instructions_var.get())

        # ── Course Documents ──────────────────────────────────────────
        docs_frame = ttk.LabelFrame(inner, text=self._t("settings_docs_section"), padding=_PAD)
        docs_frame.grid(row=row, column=0, sticky="ew", pady=(0, _PAD))
        docs_frame.columnconfigure(0, weight=1)
        row += 1

        # Re-build file listboxes (they live inside this Toplevel).
        # Snapshot the committed file list into the staging area so edits
        # inside this dialog don't touch session.classified_files until Apply.
        self._file_listboxes = {}
        self._staged_files = {
            dt: list(paths)
            for dt, paths in self._session.classified_files.items()
        }
        for doc_type in DocumentType:
            self._create_doc_section(docs_frame, doc_type)
        # Populate listboxes from the staged (not yet committed) copy
        for dt, paths in self._staged_files.items():
            lb = self._file_listboxes.get(dt)
            if lb:
                lb.delete(0, tk.END)
                for p in paths:
                    lb.insert(tk.END, Path(p).name)

        # ── Generated Outputs ─────────────────────────────────────────
        out_frame = ttk.LabelFrame(inner, text=self._t("settings_outputs_section"), padding=_PAD)
        out_frame.grid(row=row, column=0, sticky="ew", pady=(0, _PAD))
        out_frame.columnconfigure(0, weight=1)
        row += 1
        self._build_outputs_panel(out_frame, win)

        self._center_on_main(win)

    def _build_outputs_panel(
        self, parent: ttk.Frame, dialog_win: tk.Toplevel
    ) -> None:
        """Populate the Generated Outputs section inside the Settings dialog.

        Lists every file in ``<workspace>/.uacragent/outputs/`` and provides
        per-file Open, Copy, and Delete buttons plus an "Open folder" shortcut.
        The panel re-renders itself after a deletion so the list stays current.
        """
        # Resolve the outputs folder for the current session.
        ws_id     = self._session.workspace_id
        ws_folder = self._session.workspace_folder
        if not ws_id and not ws_folder:
            ttk.Label(parent, text=self._t("settings_no_workspace"),
                      foreground="gray").pack(anchor="w")
            return

        ws = workspace_paths(workspace_id=ws_id, workspace_folder=ws_folder)
        out_dir = Path(ws.outputs)

        # Container that we re-fill on every refresh
        list_frame = ttk.Frame(parent)
        list_frame.pack(fill="x")
        list_frame.columnconfigure(0, weight=1)

        # "Open folder" shortcut below the list — disabled until the folder exists
        footer = ttk.Frame(parent)
        footer.pack(fill="x", pady=(6, 0))
        open_folder_btn = ttk.Button(
            footer, text=self._t("settings_open_outputs_btn"),
            command=lambda: _open_folder_in_os(str(out_dir)),
        )
        open_folder_btn.pack(side="left")

        def _refresh() -> None:
            # Wipe and rebuild the file rows
            for w in list_frame.winfo_children():
                w.destroy()

            files: list[Path] = []
            if out_dir.exists():
                files = sorted(out_dir.iterdir(), key=lambda p: p.stat().st_mtime,
                               reverse=True)
                files = [f for f in files if f.is_file()]

            # Enable/disable the "Open folder" button based on folder existence
            open_folder_btn.configure(
                state="normal" if out_dir.exists() else "disabled")

            if not files:
                msg = (self._t("settings_no_outputs")
                       if out_dir.exists()
                       else self._t("settings_no_outputs_folder"))
                ttk.Label(list_frame, text=msg,
                          foreground="gray").grid(row=0, column=0, sticky="w",
                                                  pady=(2, 0))
                return

            for row_idx, fpath in enumerate(files):
                bg = "#f7f7f7" if row_idx % 2 == 0 else "#ffffff"

                row_f = tk.Frame(list_frame, background=bg)
                row_f.grid(row=row_idx, column=0, sticky="ew", pady=1)
                row_f.columnconfigure(0, weight=1)
                list_frame.rowconfigure(row_idx, weight=0)

                # File icon + name
                size_kb = fpath.stat().st_size / 1024
                size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else \
                           f"{size_kb/1024:.1f} MB"
                name_lbl = tk.Label(
                    row_f,
                    text=f"📄 {fpath.name}  ({size_str})",
                    background=bg, anchor="w",
                )
                name_lbl.grid(row=0, column=0, sticky="ew", padx=(4, 8))

                btn_cell = ttk.Frame(row_f)
                btn_cell.grid(row=0, column=1, padx=(0, 4), pady=2)

                # Open
                ttk.Button(
                    btn_cell, text=self._t("output_open_btn"), width=6,
                    command=lambda p=str(fpath): _open_file_in_os(p),
                ).pack(side="left", padx=(0, 3))

                # Copy to…
                def _copy_to(src: Path = fpath) -> None:
                    dest_dir = filedialog.askdirectory(
                        title=self._t("output_copy_dest_title"),
                        parent=dialog_win,
                    )
                    if not dest_dir:
                        return
                    import shutil as _shutil
                    dest = Path(dest_dir) / src.name
                    # Avoid overwriting: append _1, _2 … if the file exists
                    stem, suffix = src.stem, src.suffix
                    counter = 1
                    while dest.exists():
                        dest = Path(dest_dir) / f"{stem}_{counter}{suffix}"
                        counter += 1
                    try:
                        _shutil.copy2(str(src), str(dest))
                        messagebox.showinfo(
                            self._t("mb_copy_title"),
                            self._t("mb_copy_body").format(dest=dest),
                            parent=dialog_win)
                    except Exception as exc:
                        messagebox.showerror(
                            self._t("mb_copy_fail_title"), str(exc),
                            parent=dialog_win)

                ttk.Button(
                    btn_cell, text=self._t("output_copy_btn"), width=8,
                    command=_copy_to,
                ).pack(side="left", padx=(0, 3))

                # Delete
                def _delete(p: Path = fpath) -> None:
                    if not messagebox.askyesno(
                        self._t("mb_delete_file_title"),
                        self._t("mb_delete_file_body").format(name=p.name),
                        icon="warning", parent=dialog_win,
                    ):
                        return
                    try:
                        p.unlink()
                    except Exception as exc:
                        messagebox.showerror(
                            self._t("mb_delete_fail_title"), str(exc),
                            parent=dialog_win)
                        return
                    _refresh()

                ttk.Button(
                    btn_cell, text=self._t("output_delete_btn"), width=7,
                    command=_delete,
                ).pack(side="left")

        _refresh()

    def _create_doc_section(self, parent: ttk.Frame,
                            doc_type: DocumentType) -> None:
        label = self._t(f"doctype_{doc_type.value}")
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
        ttk.Button(btn_row, text=self._t("settings_add_files_btn"), width=7,
                   command=lambda dt=doc_type: self._on_add_files(dt)
                   ).pack(side="left", padx=(0, 3))
        ttk.Button(btn_row, text=self._t("settings_remove_files_btn"), width=7,
                   command=lambda dt=doc_type: self._on_remove_files(dt)
                   ).pack(side="left")

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
        models = models_for(provider)
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
        labels = {
            "gemini":   self._t("api_key_google"),
            "openai":   self._t("api_key_openai"),
            "deepseek": self._t("api_key_deepseek"),
        }
        self._api_key_label_var.set(labels.get(provider, "API Key:"))

        # Update hint var (also a plain StringVar)
        env_var = env_var_for(provider)
        env_key = os.environ.get(env_var, "").strip()
        self._api_key_hint_var.set(
            self._t("api_key_loaded") if env_key else self._t("api_key_not_set")
        )

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
            ttk.Label(frame, text=self._t("settings_model_label")).grid(
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
                text=self._t("settings_emb_local_hint"),
                foreground="gray", font=("TkDefaultFont", max(self._font_size() - 1, 10)),
                wraplength=400,
            ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(3, 0))
        else:
            # API-based: show a key entry field for the embedding provider.
            # Reuses the same StringVar as the LLM key section so both fields
            # stay in sync when the user types in either one.
            env_var = "GOOGLE_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
            key_var = self._gemini_key_var if provider == "gemini" else self._openai_key_var
            label   = self._t("api_key_google") if provider == "gemini" else self._t("api_key_openai")

            frame.columnconfigure(1, weight=1)
            ttk.Label(frame, text=label).grid(
                row=0, column=0, sticky="w", padx=(0, 8))

            emb_entry = ttk.Entry(frame, textvariable=key_var, show="*")
            emb_entry.grid(row=0, column=1, sticky="ew", padx=(0, 4))

            show_btn_cell: list[ttk.Button] = []
            show_btn_cell.append(ttk.Button(
                frame, text=self._t("settings_show_key"), width=5,
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
                      font=("TkDefaultFont", max(self._font_size() - 1, 10)),
                      wraplength=400,
                      ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(3, 0))

    def _has_embedding_key(self) -> bool:
        """Return True if the committed embedding provider has what it needs.

        Reads from os.environ (the committed state) rather than the live
        StringVar so that opening Settings and switching the provider without
        clicking Apply does not cause a false "key missing" rejection.
        """
        provider = os.environ.get("EMBEDDING_PROVIDER", self._emb_provider_var.get())
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
        disp = self._local_model_disp_var.get()
        size_match = re.search(r"~([\d.]+ MB)", disp)
        size_str = size_match.group(1) if size_match else "unknown size"

        from uacragent.infra.persistence import get_hf_cache_dir
        cache_dir = get_hf_cache_dir()

        return messagebox.askyesno(
            self._t("mb_dl_model_title"),
            self._t("mb_dl_model_body").format(
                model_name=model_name,
                size_str=size_str,
                cache_dir=cache_dir,
            ),
            default=messagebox.YES,
            icon=messagebox.QUESTION,
        )

    def _update_rate_suggestion(self) -> None:
        """Refresh the rate-tier suggestion label for the current provider.

        Compares the user's current tier selection against the provider's
        recommended default (stored in ``ProviderConfig.default_rate_tier``).
        Shows a blue suggestion line when they differ, a green confirmation
        when they match, and does nothing when the dialog is closed.
        """
        if not hasattr(self, "_rate_suggestion_var"):
            return  # dialog not yet built — nothing to update

        from uacragent.domain.providers import get_provider
        from uacragent.domain.rate_tiers import RATE_TIER_BY_DISPLAY, get_rate_tier

        provider_id  = self._llm_provider_var.get() or "gemini"
        provider_cfg = get_provider(provider_id)
        suggested_id = provider_cfg.default_rate_tier
        suggested    = get_rate_tier(suggested_id)

        current_disp = self._rate_tier_disp_var.get()
        current_id   = RATE_TIER_BY_DISPLAY.get(current_disp, "free")

        if current_id == suggested_id:
            text = self._t("rate_suggest_match").format(
                provider=provider_cfg.display_name)
        else:
            text = self._t("rate_suggest_mismatch").format(
                provider=provider_cfg.display_name,
                tier=suggested.display_name,
            )
        try:
            self._rate_suggestion_var.set(text)
        except Exception:  # noqa: BLE001
            pass  # StringVar destroyed between check and set — harmless

    def _on_provider_changed(self, _event: object = None) -> None:
        self._update_model_list()
        self._update_api_key_row()
        self._update_rate_suggestion()

    def _toggle_key_entry(self, entry: ttk.Entry, btn: ttk.Button | None = None) -> None:
        if entry.cget("show") == "*":
            entry.configure(show="")
            if btn:
                btn.configure(text=self._t("settings_hide_key"))
        else:
            entry.configure(show="*")
            if btn:
                btn.configure(text=self._t("settings_show_key"))

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
            title=f"Select {self._t(f'doctype_{doc_type.value}')} files",
            filetypes=_SUPPORTED_FILETYPES)
        lb = self._file_listboxes.get(doc_type)
        if lb is None:
            return
        # Work on the staging area — not the live session — so changes only
        # take effect when the user clicks Apply.
        existing = self._staged_files.setdefault(doc_type, [])
        for p in paths:
            if p not in existing:
                existing.append(p)
                lb.insert(tk.END, Path(p).name)

    def _on_remove_files(self, doc_type: DocumentType) -> None:
        lb = self._file_listboxes.get(doc_type)
        if lb is None:
            return
        indices = list(lb.curselection())
        # Work on the staging area — not the live session.
        files = self._staged_files.get(doc_type, [])
        for i in reversed(indices):
            lb.delete(i)
            if i < len(files):
                files.pop(i)

    # ------------------------------------------------------------------
    # Sync settings vars → session object
    # ------------------------------------------------------------------

    def _sync_session_from_vars(self) -> None:
        s = self._session
        # Commit the staged file list to the session.  This is the only place
        # session.classified_files is written from the settings dialog.
        s.classified_files = {dt: list(paths) for dt, paths in self._staged_files.items()}
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
            # auto-assign in _start_indexing() can use the session's UUID-based
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
        # Also reset the staging area from the freshly-loaded session so that
        # any pending (uncommitted) edits from a previous dialog session are
        # discarded and the listboxes show the true committed file list.
        if self._settings_alive():
            self._staged_files = {
                dt: list(paths)
                for dt, paths in self._session.classified_files.items()
            }
            for dt, lb in self._file_listboxes.items():
                try:
                    lb.delete(0, tk.END)
                    for p in self._staged_files.get(dt, []):
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

        # Propagate rate tier → env so Settings() picks it up on next build.
        # The model_validator in Settings translates the tier id into the three
        # concrete pipeline parameters (request_delay / max_retries / base_delay)
        # automatically, so we only need to persist the tier id here.
        from uacragent.domain.rate_tiers import RATE_TIER_BY_DISPLAY
        disp     = self._rate_tier_disp_var.get()
        tier_id  = RATE_TIER_BY_DISPLAY.get(disp, "free")
        os.environ["RATE_TIER"] = tier_id
        # Force the agent to be reconstructed so the new rate parameters take
        # effect immediately on the next chat or generation request.
        self._agent = None

        # Check that the active LLM provider has its key
        env_var = env_var_for(provider)
        return bool(os.environ.get(env_var, ""))

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
        # Clear the "fill in settings and click Apply" hint once a course name
        # is present — the session is now properly set up.
        if self._session.course_name:
            self._session_status_var.set("")

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
                self._settings_status_var.set(self._t("settings_applying"))
            except tk.TclError:
                pass
        self._start_indexing(show_error_dialog=True)
