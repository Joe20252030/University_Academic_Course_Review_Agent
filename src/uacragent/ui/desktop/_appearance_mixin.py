"""Appearance, theming, and App Settings dialog methods."""
from __future__ import annotations

import os
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, ttk

from uacragent.infra.persistence import (
    get_app_appearance, set_app_appearance,
    get_app_data_dir, set_app_data_dir,
)

from ._custom_widgets import _RoundedChip
from ._ui_constants import _STRINGS, _THEME_COLORS, _FONT_SIZE_VALUES


class AppearanceMixin:
    """Mixin: appearance, theming, language switching, and app-settings dialog."""
    def _t(self, key: str) -> str:
        """Return the UI string for *key* in the current language."""
        lang = self._language_var.get() if hasattr(self, "_language_var") else "en"
        return (_STRINGS.get(lang) or _STRINGS["en"]).get(
            key, _STRINGS["en"].get(key, key)
        )

    def _load_app_appearance(self) -> None:
        """Load persisted appearance settings into the StringVars."""
        try:
            prefs = get_app_appearance()
            self._color_mode_var.set(prefs.get("color_mode", "light"))
            self._font_size_var.set(prefs.get("font_size",  "medium"))
            self._language_var.set(prefs.get("language",   "en"))
        except Exception:
            pass  # keep defaults on any error

    def _apply_theme(self, reconfigure_tags: bool = True) -> None:
        """Apply the current color mode to all widgets."""
        mode = self._color_mode_var.get()
        c    = _THEME_COLORS.get(mode, _THEME_COLORS["light"])
        style = ttk.Style(self)

        # ── Primary.TButton — gold Send / Apply ──────────────────────────
        style.configure("Primary.TButton",
            background=c["btn_primary_bg"],
            foreground=c["btn_primary_fg"],
            relief="flat", borderwidth=0, padding=(14, 7),
        )
        style.map("Primary.TButton",
            background=[("active", "#e8961a"), ("pressed", "#d4880f"),
                        ("disabled", "#c8c8c8")],
            foreground=[("active",  c["btn_primary_fg"]),
                        ("disabled", "#888888")],
        )

        # ── Chip.TButton — quick-action chips ────────────────────────────
        # Defined in both modes so the style is always available.
        style.configure("Chip.TButton",
            background=c["qa_bg"],
            foreground=c["qa_fg"],
            relief="flat", borderwidth=0,
            padding=(12, 5),
        )
        style.map("Chip.TButton",
            background=[("active", c["qa_bg_hover"]), ("pressed", c["qa_bg_hover"])],
            foreground=[("active", c["qa_fg"])],
        )

        # (NewSession.TButton and SidebarBottom.TButton removed — sidebar
        # buttons are now canvas-drawn _RoundedChip widgets updated below)

        if mode == "dark":
            style.theme_use("clam")
            # Base defaults
            style.configure(".",
                background=c["window_bg"],
                foreground=c["text_fg"],
                fieldbackground=c["text_bg"],
                troughcolor=c["window_bg"],
                selectbackground=c["lb_sel_bg"],
                selectforeground=c["lb_sel_fg"],
                bordercolor="#1e3566",
                darkcolor=c["window_bg"],
                lightcolor=c["text_bg"],
            )
            style.configure("TFrame",      background=c["window_bg"])
            style.configure("TLabel",      background=c["window_bg"],
                                           foreground=c["text_fg"])
            style.configure("TLabelframe", background=c["window_bg"],
                                           foreground=c["text_fg"])
            style.configure("TLabelframe.Label",
                            background=c["window_bg"], foreground=c["text_fg"])

            # Sidebar panel
            style.configure("Sidebar.TFrame", background=c["sidebar_bg"])
            style.configure("Sidebar.TLabel",
                            background=c["sidebar_bg"], foreground=c["lb_fg"])

            # Standard buttons — flat, navy tinted
            style.configure("TButton",
                background=c["text_bg"], foreground=c["text_fg"],
                relief="flat", borderwidth=0, padding=(10, 6),
            )
            style.map("TButton",
                background=[("active", "#1e3a6e"), ("pressed", "#162f58")],
                foreground=[("active", c["text_fg"])],
            )
            style.configure("Gear.TButton",
                background=c["window_bg"], foreground=c["text_fg"],
                relief="flat", borderwidth=0, padding=(4, 2),
            )
            style.map("Gear.TButton",
                background=[("active", "#162f58")],
            )

            style.configure("TEntry",
                fieldbackground=c["input_bg"],
                foreground=c["text_fg"],
                insertcolor=c["text_fg"],
                bordercolor="#1e3566",
            )
            style.configure("TCombobox",
                fieldbackground=c["input_bg"],
                foreground=c["text_fg"],
                background=c["text_bg"],
                selectbackground=c["lb_sel_bg"],
                selectforeground=c["lb_sel_fg"],
            )
            style.map("TCombobox",
                fieldbackground=[("readonly", c["input_bg"])],
                foreground=[("readonly", c["text_fg"])],
                selectbackground=[("readonly", c["lb_sel_bg"])],
            )
            style.configure("TScrollbar",
                background=c["sidebar_bg"],
                troughcolor=c["window_bg"],
                arrowcolor=c["status_fg"],
                borderwidth=0,
            )
            style.configure("TSeparator", background="#1e3566")
            style.configure("TRadiobutton",
                background=c["window_bg"], foreground=c["text_fg"])
            style.map("TRadiobutton",
                background=[("active", c["window_bg"])],
                foreground=[("active", c["text_fg"])],
            )
            style.configure("TCheckbutton",
                background=c["window_bg"], foreground=c["text_fg"])

            self.configure(background=c["window_bg"])
            self._paned.configure(background=c["window_bg"])

        else:
            # Restore the platform's native theme for light mode
            try:
                style.theme_use(self._default_ttk_theme)
            except tk.TclError:
                style.theme_use("default")

            # Re-apply custom styles that survive a theme change
            style.configure("Sidebar.TFrame", background=c["sidebar_bg"])
            style.configure("Sidebar.TLabel",
                            background=c["sidebar_bg"], foreground=c["lb_fg"])
            style.configure("Gear.TButton", padding=(4, 2))
            # Re-apply chip + primary styles explicitly (native theme resets them)
            style.configure("Chip.TButton",
                background=c["qa_bg"], foreground=c["qa_fg"],
                relief="flat", borderwidth=0, padding=(12, 5),
            )
            style.map("Chip.TButton",
                background=[("active", c["qa_bg_hover"]),
                            ("pressed", c["qa_bg_hover"])],
                foreground=[("active", c["qa_fg"])],
            )

            try:
                self.configure(background=c["window_bg"])
            except Exception:
                pass
            self._paned.configure(background=c["window_bg"])

        # ── Non-ttk widgets need direct configuration ─────────────────
        # Message bubble canvas and frame backgrounds (individual bubble
        # widget colours are applied fresh on each _append_chat call)
        try:
            self._msg_canvas.configure(bg=c["text_bg"])
            self._msg_frame.configure(bg=c["text_bg"])
        except Exception:
            pass
        # input_text colours are managed by _redraw_input_block_canvas below
        # CustomSessionList handles its own colours via update_colors()
        try:
            self._session_list.update_colors(c)
        except Exception:
            pass
        # Sidebar sits on the window background — no card, just plain bg.
        _wbg = c["window_bg"]
        try:
            self._sidebar_frame.configure(bg=_wbg)
        except Exception:
            pass
        # Chat pane outer frame also uses window_bg so the card margin shows.
        try:
            self._chat_frame.configure(bg=_wbg)
            self._hist_canvas.configure(bg=_wbg)
        except Exception:
            pass
        # Chat top bar lives inside _hist_inner (the white card).
        # _top_bar_info_area is aliased to _chat_top_bar, so one call covers both.
        _card_bg = c["text_bg"]
        try:
            self._chat_top_bar.configure(bg=_card_bg)
        except Exception:
            pass
        # Title and status labels are direct children of top_bar (stored refs).
        try:
            self._header_course_lbl.configure(
                bg=_card_bg, fg=c.get("text_fg", "#1a2744"))
        except Exception:
            pass
        try:
            self._session_status_lbl.configure(
                bg=_card_bg, fg=c.get("status_fg", "#6b7280"))
        except Exception:
            pass
        # Sidebar toggle icon — parent_bg=text_bg since it lives inside the card
        try:
            self._toggle_sidebar_btn.update_colors(c, parent_bg=_card_bg)
        except Exception:
            pass
        # Sidebar bottom separator (inside the rounded sidebar card)
        try:
            self._sidebar_sep.configure(bg=c.get("input_border", "#cdd4e8"))
        except Exception:
            pass
        # Sidebar widgets sit on window_bg — ghost buttons blend into it.
        _wbg = c["window_bg"]
        _fg  = c.get("lb_fg", "#1a2744")
        # New Session chip
        try:
            self._new_session_btn.update_style(
                chip_bg=_wbg,
                chip_fg=_fg,
                hover_bg=c.get("lb_hover_bg", "#dfe4f0"),
                parent_bg=_wbg,
            )
        except Exception:
            pass
        # App Settings chip
        try:
            self._gear_btn.update_style(
                chip_bg=_wbg,
                chip_fg=_fg,
                hover_bg=c.get("lb_hover_bg", "#dfe4f0"),
                parent_bg=_wbg,
            )
        except Exception:
            pass
        # "Sessions" label and search bar
        try:
            self._sessions_label.configure(
                bg=_wbg, fg=c.get("status_fg", "#9aa5be"))
            self._search_outer.configure(bg=_wbg)
            self._redraw_search_cv()
        except Exception:
            pass
        # Re-apply Session Settings visibility after theme colours are reset
        try:
            if self._sess_settings_visible:
                self._show_sess_settings()
            else:
                self._hide_sess_settings()
        except Exception:
            pass
        # Flat chat canvas — re-sync size and bg
        try:
            self._redraw_hist_canvas()
        except Exception:
            pass

        # ── Overlay scrollbar (chat only; session list handles its own) ──
        # sb_bg is set to match text_bg in the theme so no track is visible
        _sb_col = c.get("sb_color", "#9aa5be")
        _sb_bg  = c.get("sb_bg", c["text_bg"])
        try:
            self._chat_vsb.update_style(_sb_col, _sb_bg)
        except Exception:
            pass

        # ── Input block effort label + chip ──────────────────────────────────
        _inp_bg  = c["input_bg"]
        _inp_fg  = c["input_fg"]
        _st_fg   = c.get("status_fg", "#6b7280")
        _act_bg  = c.get("qa_bg", _inp_bg)
        _border  = c.get("input_border", "#cdd4e8")
        # "Effort:" label (tk.Label only — no radio buttons any more)
        for _w in getattr(self, "_effort_flat_widgets", []):
            try:
                _w.configure(bg=_inp_bg, fg=_st_fg)
            except Exception:
                pass
        # Effort level chip (single dropdown trigger)
        _act_hov = c.get("qa_bg_hover", _act_bg)
        try:
            self._effort_chip.update_style(
                chip_bg=_act_bg, chip_fg=_inp_fg,
                hover_bg=_act_hov, parent_bg=_inp_bg,
                outline=_border,
            )
        except Exception:
            pass
        # Reasoning mode chip (same visual style as effort chip)
        try:
            self._reasoning_chip.update_style(
                chip_bg=_act_bg, chip_fg=_inp_fg,
                hover_bg=_act_hov, parent_bg=_inp_bg,
                outline=_border,
            )
        except Exception:
            pass
        # Session Settings (_RoundedChip)
        try:
            self._sess_settings_btn.update_style(
                chip_bg=_inp_bg, chip_fg=_inp_fg,
                hover_bg=_act_bg, parent_bg=_inp_bg,
                outline=_border,
            )
        except Exception:
            pass
        # Send button (_RoundedChip, primary colours)
        _prim_bg  = c["btn_primary_bg"]
        _prim_fg  = c["btn_primary_fg"]
        _prim_hov = c.get("btn_primary_hover", "#e8961a")
        try:
            self._send_btn.update_style(
                chip_bg=_prim_bg, chip_fg=_prim_fg,
                hover_bg=_prim_hov, parent_bg=_inp_bg,
            )
        except Exception:
            pass
        # Cancel button (_RoundedChip, red danger colours)
        _canc_bg  = c.get("btn_cancel_bg",    "#e53e3e")
        _canc_fg  = c.get("btn_cancel_fg",    "#ffffff")
        _canc_hov = c.get("btn_cancel_hover", "#c53030")
        try:
            self._cancel_btn.update_style(
                chip_bg=_canc_bg, chip_fg=_canc_fg,
                hover_bg=_canc_hov, parent_bg=_inp_bg,
            )
        except Exception:
            pass

        # ── Rounded canvases ───────────────────────────────────────────
        # _redraw_hist_canvas() repaints the unified card rounded rect.
        try:
            self._redraw_list_canvas()
        except Exception:
            pass
        try:
            self._redraw_hist_canvas()
        except Exception:
            pass
        try:
            self._redraw_input_block_canvas()   # also calls _redraw_input_text_cv
        except Exception:
            pass

        # ── Search / upload button state after theme colours are reset ────────
        try:
            self._refresh_search_btn()
        except Exception:
            pass
        try:
            self._update_tool_btns()
        except Exception:
            pass

        if reconfigure_tags:
            self._reconfigure_chat_tags()

    def _reconfigure_chat_tags(self) -> None:
        """Re-render existing chat bubbles at the current font size.

        Chat messages are ``tk.Label`` widgets created at message-append time
        with the font size that was active then.  When the user changes the
        font size those already-created labels are not automatically updated by
        tkinter's named-font mechanism (they carry explicit tuple fonts, not
        named-font references).

        The cleanest fix is to destroy all bubble widgets and re-append every
        message from the session's chat history, which calls ``_append_chat``
        fresh and picks up the new ``_font_size()`` value.  This is exactly
        what ``_replay_chat_history`` does.

        Only runs when a session with loaded history is active; otherwise it
        is a fast no-op.
        """
        try:
            if not getattr(self, "_session", None):
                return
            if not self._session.chat_history:
                return
            # Clear existing bubble widgets and re-render from stored history.
            self._clear_chat()
            self._replay_chat_history()
        except Exception:
            pass

    def _font_size(self) -> int:
        """Return the current font size as an integer."""
        return _FONT_SIZE_VALUES.get(self._font_size_var.get(), 13)

    def _apply_font_size(self) -> None:
        """Apply the selected font size to the named font and key widgets."""
        size = self._font_size()
        # Update the named default font — propagates to all ttk widgets
        try:
            tkfont.nametofont("TkDefaultFont").configure(size=size)
        except Exception:
            pass

        # ── Scale sidebar chip fonts ──────────────────────────────────────
        try:
            self._new_session_btn.update_style(font=("TkDefaultFont", size, "bold"))
        except Exception:
            pass
        try:
            self._gear_btn.update_style(font=("TkDefaultFont", size))
        except Exception:
            pass
        try:
            self._sessions_label.configure(font=("TkDefaultFont", max(size - 2, 9)))
        except Exception:
            pass
        try:
            self._search_entry.configure(font=("TkDefaultFont", max(size - 1, 10)))
            self._redraw_search_cv()   # resize the entry window inside the canvas
        except Exception:
            pass
        try:
            # Session title: 1 pt larger than body for visual hierarchy
            self._header_course_lbl.configure(
                font=("TkDefaultFont", size + 1, "bold"))
        except Exception:
            pass
        try:
            # Quick-action label and chips scale with body font
            for _i, _c in enumerate(self._qa_chips):
                if _i == 0:
                    _c.configure(font=("TkDefaultFont", size))   # "Quick Actions:" label
                elif hasattr(_c, "update_style"):
                    _c.update_style(font=("TkDefaultFont", size))
        except Exception:
            pass

        # (Gear.TButton removed — App Settings is now a _RoundedChip updated above)
        # Widgets with explicit font tuples must be updated individually
        # (message bubbles use named-font references; new bubbles pick up size
        # automatically via _font_size() — existing bubbles retain creation size)
        try:
            self._input_text.configure(font=("TkDefaultFont", size))
        except Exception:
            pass
        # Re-sync the input block height after the font size changes the text
        # widget's required height.  Schedule via after() so the widget has
        # time to recalculate its own geometry first.
        try:
            self.after(60, self._auto_resize_input)
        except Exception:
            pass
        # Secondary info labels: 1pt below body text, minimum 10pt
        _sub = max(size - 1, 10)
        try:
            self._session_status_lbl.configure(font=("TkDefaultFont", _sub))
        except Exception:
            pass
        # _busy_label removed; thinking progress is shown in the chat window.
        # Flat native widgets in input block (effort label + chip)
        _ctrl_size = max(size - 1, 11)
        for _w in getattr(self, "_effort_flat_widgets", []):
            try:
                _w.configure(font=("TkDefaultFont", _ctrl_size))
            except Exception:
                pass
        try:
            self._effort_chip.update_style(font=("TkDefaultFont", _ctrl_size))
        except Exception:
            pass
        # Reasoning mode chip (same control size as effort chip)
        try:
            self._reasoning_chip.update_style(font=("TkDefaultFont", _ctrl_size))
        except Exception:
            pass
        # Session Settings (_RoundedChip)
        try:
            self._sess_settings_btn.update_style(font=("TkDefaultFont", _ctrl_size))
        except Exception:
            pass
        # Send button (_RoundedChip)
        try:
            self._send_btn.update_style(font=("TkDefaultFont", _ctrl_size, "bold"))
        except Exception:
            pass
        # Cancel button (_RoundedChip) — same bold style as Send
        try:
            self._cancel_btn.update_style(font=("TkDefaultFont", _ctrl_size, "bold"))
        except Exception:
            pass
        # Search and upload icon buttons
        try:
            for _btn in (self._search_btn, self._upload_btn):
                _btn.update_style(font=("TkDefaultFont", max(_ctrl_size, 12)))
        except Exception:
            pass
        # Re-apply tag fonts with the new size
        self._reconfigure_chat_tags()

    def _apply_language(self) -> None:
        """Update every registered i18n widget to the current language."""
        for target, attr, key in self._i18n_widgets:
            try:
                target.configure(**{attr: self._t(key)})
            except Exception:
                pass
        # Effort chip text is dynamic (current level name changes with language)
        try:
            self._effort_chip.set_text(self._effort_chip_text())
        except Exception:
            pass
        # Reasoning chip text also uses localised mode names
        try:
            self._reasoning_chip.set_text(self._reasoning_chip_text())
        except Exception:
            pass
        # Update the ⋯ popup menu labels in the session list
        try:
            self._session_list.set_menu_labels(
                self._t("rename"), self._t("delete")
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # App Settings dialog  (global, not per-session)
    # ------------------------------------------------------------------

    def _open_app_settings(self) -> None:
        """Open the App Settings dialog (appearance + data directory)."""
        # Prevent opening multiple simultaneous instances
        if (hasattr(self, "_app_settings_win")
                and self._app_settings_win is not None
                and self._app_settings_win.winfo_exists()):
            self._app_settings_win.lift()
            self._app_settings_win.focus_set()
            return

        c      = _THEME_COLORS.get(self._color_mode_var.get(), _THEME_COLORS["light"])
        _wbg   = c["window_bg"]
        _fg    = c["text_fg"]
        _sfg   = c.get("status_fg", "#6b7280")
        _border= c["input_border"]
        _ibg   = c["input_bg"]
        _ifg   = c["input_fg"]
        _pbg   = c["btn_primary_bg"]
        _pfg   = c["btn_primary_fg"]
        _phov  = c.get("btn_primary_hover", _pbg)
        _sz    = self._font_size()
        _nsz   = max(_sz - 1, 10)

        win = self._make_toplevel()
        self._app_settings_win = win
        win.title(self._t("app_settings_title"))
        win.configure(bg=_wbg)
        win.resizable(False, False)
        win.grab_set()

        # Snapshot current appearance so Cancel can revert live previews.
        _saved_color = self._color_mode_var.get()
        _saved_font  = self._font_size_var.get()
        _saved_lang  = self._language_var.get()

        _cbg   = c.get("text_bg", "#ffffff")    # card fill
        _brd   = c.get("input_border", "#cdd4e8")

        # Outer padding frame (window_bg) → inner card (text_bg)
        outer = tk.Frame(win, bg=_wbg, padx=12, pady=12)
        outer.pack(fill="both", expand=True)

        frm = tk.Frame(outer, bg=_cbg, padx=20, pady=18,
                       highlightthickness=1, highlightbackground=_brd)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)
        row = 0

        # ── Appearance section ────────────────────────────────────────
        # Section header label
        tk.Label(frm, text=self._t("appearance_section"),
                 bg=_cbg, fg=_fg,
                 font=("TkDefaultFont", _sz, "bold"),
                 anchor="w").grid(row=row, column=0, columnspan=3,
                                  sticky="w", pady=(0, 10))
        row += 1
        # Thin line under header
        tk.Frame(frm, bg=_border, height=1).grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        row += 1

        # Color mode
        tk.Label(frm, text=self._t("color_mode_label"),
                 bg=_cbg, fg=_fg,
                 font=("TkDefaultFont", _sz)).grid(
            row=row, column=0, sticky="w", padx=(0, 10), pady=(0, 8))
        _cm_row = tk.Frame(frm, bg=_cbg)
        _cm_row.grid(row=row, column=1, columnspan=2, sticky="w", pady=(0, 8))
        for _val, _key in [("light", "light_mode"), ("dark", "dark_mode")]:
            tk.Radiobutton(
                _cm_row, text=self._t(_key), value=_val,
                variable=self._color_mode_var,
                command=self._apply_theme,
                bg=_cbg, fg=_fg,
                activebackground=_cbg, activeforeground=_fg,
                selectcolor=_cbg,
                relief="flat", bd=0, highlightthickness=0,
            ).pack(side="left", padx=(0, 12))
        row += 1

        # Font size
        tk.Label(frm, text=self._t("font_size_label"),
                 bg=_cbg, fg=_fg,
                 font=("TkDefaultFont", _sz)).grid(
            row=row, column=0, sticky="w", padx=(0, 10), pady=(0, 8))
        _fs_row = tk.Frame(frm, bg=_cbg)
        _fs_row.grid(row=row, column=1, columnspan=2, sticky="w", pady=(0, 8))
        for _val, _key in [("small", "font_small"), ("medium", "font_medium"),
                            ("large", "font_large")]:
            tk.Radiobutton(
                _fs_row, text=self._t(_key), value=_val,
                variable=self._font_size_var,
                command=self._apply_font_size,
                bg=_cbg, fg=_fg,
                activebackground=_cbg, activeforeground=_fg,
                selectcolor=_cbg,
                relief="flat", bd=0, highlightthickness=0,
            ).pack(side="left", padx=(0, 12))
        row += 1

        # Language
        tk.Label(frm, text=self._t("language_label"),
                 bg=_cbg, fg=_fg,
                 font=("TkDefaultFont", _sz)).grid(
            row=row, column=0, sticky="w", padx=(0, 10), pady=(0, 10))
        _lang_row = tk.Frame(frm, bg=_cbg)
        _lang_row.grid(row=row, column=1, columnspan=2, sticky="w", pady=(0, 10))
        for _val, _display in [("en", "English"), ("zh_CN", "中文（简体）")]:
            tk.Radiobutton(
                _lang_row, text=_display, value=_val,
                variable=self._language_var,
                bg=_cbg, fg=_fg,
                activebackground=_cbg, activeforeground=_fg,
                selectcolor=_cbg,
                relief="flat", bd=0, highlightthickness=0,
            ).pack(side="left", padx=(0, 12))
        row += 1

        # Separator
        tk.Frame(frm, bg=_border, height=1).grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        row += 1

        # ── App data folder section ───────────────────────────────────
        tk.Label(frm, text=self._t("app_data_label"),
                 bg=_cbg, fg=_fg,
                 font=("TkDefaultFont", _sz, "bold"),
                 anchor="w").grid(row=row, column=0, columnspan=3,
                                  sticky="w", pady=(0, 4))
        row += 1
        tk.Label(frm, text=self._t("app_data_hint"),
                 bg=_cbg, fg=_sfg,
                 font=("TkDefaultFont", _nsz),
                 justify="left", anchor="w",
                 ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 8))
        row += 1

        path_var = tk.StringVar(value=self._app_data_dir_var.get())
        path_entry = tk.Entry(
            frm, textvariable=path_var, width=42,
            bg=_ibg, fg=_ifg, insertbackground=_ifg,
            relief="flat", bd=0,
            font=("TkDefaultFont", _sz),
            highlightthickness=1,
            highlightbackground=_border,
            highlightcolor=_pbg,
        )
        path_entry.grid(row=row, column=0, sticky="ew", padx=(0, 6), ipady=4)

        def _browse() -> None:
            folder = filedialog.askdirectory(
                title="Select app data folder",
                initialdir=path_var.get() or str(Path.home()),
            )
            if folder:
                path_var.set(folder)

        _browse_chip = _RoundedChip(
            frm, text="Browse…",
            chip_bg=_cbg, chip_fg=_fg,
            parent_bg=_cbg,
            font=("TkDefaultFont", _sz),
            padx=12, pady=4,
            outline=_border, outline_width=1,
            hover_bg=c.get("qa_bg", "#edf0f8"),
            command=_browse,
        )
        _browse_chip.grid(row=row, column=1, padx=(0, 4), pady=2)
        row += 1

        # Separator before buttons
        tk.Frame(frm, bg=_border, height=1).grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=(14, 12))
        row += 1

        # ── Buttons ───────────────────────────────────────────────────
        btn_row = tk.Frame(frm, bg=_cbg)
        btn_row.grid(row=row, column=0, columnspan=3, sticky="e")

        def _save() -> None:
            # Persist appearance settings
            set_app_appearance(
                self._color_mode_var.get(),
                self._font_size_var.get(),
                self._language_var.get(),
            )
            # Apply language now (was not applied live to avoid mid-dialog churn)
            self._apply_language()
            # Persist app data dir if changed
            chosen = path_var.get().strip()
            if chosen:
                p = Path(chosen)
                try:
                    p.mkdir(parents=True, exist_ok=True)
                except Exception as exc:
                    self._show_info_dialog(self._t("mb_cannot_create_folder"), str(exc))
                    return
                set_app_data_dir(p)
                self._app_data_dir_var.set(str(p.resolve()))
            win.destroy()

        def _cancel() -> None:
            # Revert live-preview appearance changes
            self._color_mode_var.set(_saved_color)
            self._font_size_var.set(_saved_font)
            self._language_var.set(_saved_lang)
            self._apply_theme()
            self._apply_font_size()
            win.destroy()

        _RoundedChip(
            btn_row, text=self._t("save"),
            chip_bg=_pbg, chip_fg=_pfg,
            parent_bg=_cbg,
            font=("TkDefaultFont", _sz, "bold"),
            padx=16, pady=6,
            hover_bg=_phov,
            command=_save,
        ).pack(side="left", padx=(0, 8))
        _RoundedChip(
            btn_row, text=self._t("cancel_btn"),
            chip_bg=_cbg, chip_fg=_fg,
            parent_bg=_cbg,
            font=("TkDefaultFont", _sz),
            padx=16, pady=6,
            outline=_border, outline_width=1,
            hover_bg=c.get("qa_bg", "#edf0f8"),
            command=_cancel,
        ).pack(side="left")

        self._center_on_main(win)

    # ------------------------------------------------------------------
    # Settings field helpers
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Provider / model helpers
    # ------------------------------------------------------------------

