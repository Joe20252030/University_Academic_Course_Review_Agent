"""Appearance, theming, and App Settings dialog methods."""
from __future__ import annotations

import os
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from uacragent.infra.persistence import (
    get_app_appearance, set_app_appearance,
    get_app_data_dir, set_app_data_dir,
)

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

        # ── NewSession.TButton — full-width top-of-sidebar "+" button ─────
        _ns_bg = c.get("new_session_bg", c["btn_primary_bg"])
        _ns_fg = c.get("new_session_fg", c["btn_primary_fg"])
        # Use the current font-size preference so a theme switch doesn't reset
        # the button back to the creation-time size.
        _ns_font_size = self._font_size() if hasattr(self, "_font_size_var") else 13
        style.configure("NewSession.TButton",
            background=_ns_bg,
            foreground=_ns_fg,
            relief="flat", borderwidth=0,
            padding=(10, 7),
            font=("TkDefaultFont", _ns_font_size, "bold"),
        )
        style.map("NewSession.TButton",
            background=[("active",  c.get("new_session_bg_hover", "#e8961a")),
                        ("pressed", c.get("new_session_bg_hover", "#d4880f"))],
            foreground=[("active", _ns_fg)],
        )

        # ── SidebarBottom.TButton — App Settings at bottom of sidebar ─────
        _sb_bottom_bg = c.get("sidebar_btn_bg", c["sidebar_bg"])
        _sb_bottom_fg = c.get("sidebar_btn_fg", c.get("lb_fg", "#1a2744"))
        style.configure("SidebarBottom.TButton",
            background=_sb_bottom_bg,
            foreground=_sb_bottom_fg,
            relief="flat", borderwidth=0,
            padding=(10, 7),
            font=("TkDefaultFont", _ns_font_size),
        )
        style.map("SidebarBottom.TButton",
            background=[("active",  c.get("lb_hover_bg", "#dfe4f0")),
                        ("pressed", c.get("lb_hover_bg", "#dfe4f0"))],
            foreground=[("active", _sb_bottom_fg)],
        )

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
            self._paned.configure(background=c["paned_bg"])

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
            self._paned.configure(background=c["paned_bg"])

        # ── Non-ttk widgets need direct configuration ─────────────────
        try:
            self._chat_text.configure(
                bg=c["text_bg"], fg=c["text_fg"],
                insertbackground=c["text_fg"],
            )
        except Exception:
            pass
        # input_text colours are managed by _redraw_input_block_canvas below
        # CustomSessionList handles its own colours via update_colors()
        try:
            self._session_list.update_colors(c)
        except Exception:
            pass
        # Sidebar frame direct background (covers macOS native theme)
        try:
            self._sidebar_frame.configure(background=c["sidebar_bg"])
        except Exception:
            pass
        # Chat top bar and info area live inside _hist_inner (the white card),
        # so they all use text_bg as their background.
        _card_bg = c["text_bg"]
        for _tb_widget in ("_chat_top_bar", "_top_bar_info_area"):
            try:
                getattr(self, _tb_widget).configure(bg=_card_bg)
            except Exception:
                pass
        # Title / status labels inside the info area
        try:
            for _lbl in self._top_bar_info_area.winfo_children():
                _lbl.configure(bg=_card_bg)
                if _lbl is self._session_status_lbl:
                    _lbl.configure(fg=c.get("status_fg", "#6b7280"))
                else:
                    _lbl.configure(fg=c.get("text_fg", "#1a2744"))
        except Exception:
            pass
        # Sidebar toggle icon — parent_bg=text_bg since it lives inside the card
        try:
            self._toggle_sidebar_btn.update_colors(c, parent_bg=_card_bg)
        except Exception:
            pass
        # Sidebar bottom separator
        try:
            self._sidebar_sep.configure(bg=c["paned_bg"])
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
        try:
            self._effort_chip.update_style(
                chip_bg=_act_bg, chip_fg=_inp_fg,
                hover_bg=_act_bg, parent_bg=_inp_bg,
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
        # _redraw_hist_canvas() also updates _chat_separator and _card_sep.
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

        if reconfigure_tags:
            self._reconfigure_chat_tags()

    def _reconfigure_chat_tags(self) -> None:
        """Re-apply chat-bubble colours for the current theme and font size."""
        c    = _THEME_COLORS.get(self._color_mode_var.get(), _THEME_COLORS["light"])
        size = self._font_size()
        lbl_font  = ("TkDefaultFont", size - 1, "bold")
        sys_font  = ("TkDefaultFont", size - 1, "italic")
        try:
            self._chat_text.tag_configure(
                "user_label",
                foreground=c["user_fg"],
                font=lbl_font,
                spacing1=14, spacing3=2,
            )
            self._chat_text.tag_configure(
                "user_body",
                foreground=c["user_fg"],
                lmargin1=12, lmargin2=12,
                spacing3=10,
            )
            self._chat_text.tag_configure(
                "assistant_label",
                foreground=c["assist_fg"],
                font=lbl_font,
                spacing1=14, spacing3=2,
            )
            self._chat_text.tag_configure(
                "assistant_body",
                foreground=c["assist_body"],
                lmargin1=12, lmargin2=12,
                spacing3=10,
            )
            self._chat_text.tag_configure(
                "system_body",
                foreground=c["system_fg"],
                font=sys_font,
                lmargin1=12, lmargin2=12,
                spacing1=4, spacing3=8,
            )
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

        # ── Scale sidebar button and chrome element fonts ─────────────────
        # These were not previously in the scaling path so they appeared stuck
        # at their creation-time size on platforms where the global TkDefaultFont
        # change does not auto-propagate to ttk style fonts (Windows / Linux).
        # Explicitly setting them here ensures consistent scaling on all platforms.
        try:
            _s = ttk.Style(self)
            _s.configure("NewSession.TButton",    font=("TkDefaultFont", size, "bold"))
            _s.configure("SidebarBottom.TButton", font=("TkDefaultFont", size))
        except Exception:
            pass
        try:
            # Session title: 1 pt larger than body for visual hierarchy
            for _lbl in self._top_bar_info_area.winfo_children():
                if _lbl is not self._session_status_lbl:
                    _lbl.configure(font=("TkDefaultFont", size + 1, "bold"))
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

        # Gear button: use a dedicated style so it appears noticeably larger
        # than the surrounding text buttons (size + 4 gives a prominent icon).
        try:
            ttk.Style(self).configure("Gear.TButton", font=("TkDefaultFont", size + 4))
        except Exception:
            pass
        # Widgets with explicit font tuples must be updated individually
        try:
            self._chat_text.configure(font=("TkDefaultFont", size))
        except Exception:
            pass
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

        win = tk.Toplevel(self)
        self._app_settings_win = win
        win.title(self._t("app_settings_title"))
        win.resizable(False, False)
        win.grab_set()

        # Snapshot current appearance so Cancel can revert live previews.
        _saved_color = self._color_mode_var.get()
        _saved_font  = self._font_size_var.get()
        _saved_lang  = self._language_var.get()

        frm = ttk.Frame(win, padding=16)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)
        row = 0

        # ── Appearance section ────────────────────────────────────────
        app_frm = ttk.LabelFrame(frm, text=self._t("appearance_section"), padding=10)
        app_frm.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 14))
        app_frm.columnconfigure(1, weight=1)
        row += 1

        # Color mode
        ttk.Label(app_frm, text=self._t("color_mode_label")).grid(
            row=0, column=0, sticky="w", padx=(0, 10), pady=(0, 6))
        _cm_row = ttk.Frame(app_frm)
        _cm_row.grid(row=0, column=1, sticky="w", pady=(0, 6))
        for _val, _key in [("light", "light_mode"), ("dark", "dark_mode")]:
            ttk.Radiobutton(
                _cm_row, text=self._t(_key), value=_val,
                variable=self._color_mode_var,
                command=self._apply_theme,       # live preview
            ).pack(side="left", padx=(0, 12))

        # Font size
        ttk.Label(app_frm, text=self._t("font_size_label")).grid(
            row=1, column=0, sticky="w", padx=(0, 10), pady=(0, 6))
        _fs_row = ttk.Frame(app_frm)
        _fs_row.grid(row=1, column=1, sticky="w", pady=(0, 6))
        for _val, _key in [("small", "font_small"), ("medium", "font_medium"),
                            ("large", "font_large")]:
            ttk.Radiobutton(
                _fs_row, text=self._t(_key), value=_val,
                variable=self._font_size_var,
                command=self._apply_font_size,   # live preview
            ).pack(side="left", padx=(0, 12))

        # Language
        ttk.Label(app_frm, text=self._t("language_label")).grid(
            row=2, column=0, sticky="w", padx=(0, 10))
        _lang_row = ttk.Frame(app_frm)
        _lang_row.grid(row=2, column=1, sticky="w")
        for _val, _display in [("en", "English"), ("zh_CN", "中文（简体）")]:
            ttk.Radiobutton(
                _lang_row, text=_display, value=_val,
                variable=self._language_var,
                # Language updates apply on Save only (avoids mid-dialog relabel)
            ).pack(side="left", padx=(0, 12))

        # ── App data folder section ───────────────────────────────────
        _app_note_sz = max(self._font_size() - 1, 10)
        ttk.Label(frm, text=self._t("app_data_label"),
                  font=("TkDefaultFont", self._font_size(), "bold")
                  ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 4))
        row += 1
        ttk.Label(frm, text=self._t("app_data_hint"),
                  foreground="gray", font=("TkDefaultFont", _app_note_sz),
                  ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 8))
        row += 1

        path_var = tk.StringVar(value=self._app_data_dir_var.get())
        path_entry = ttk.Entry(frm, textvariable=path_var, width=42)
        path_entry.grid(row=row, column=0, sticky="ew", padx=(0, 4))

        def _browse() -> None:
            folder = filedialog.askdirectory(
                title="Select app data folder",
                initialdir=path_var.get() or str(Path.home()),
            )
            if folder:
                path_var.set(folder)

        ttk.Button(frm, text="Browse…", command=_browse
                   ).grid(row=row, column=1, padx=(0, 4))
        row += 1

        # ── Buttons ───────────────────────────────────────────────────
        btn_row = ttk.Frame(frm)
        btn_row.grid(row=row, column=0, columnspan=3, sticky="e", pady=(14, 0))

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
                    messagebox.showerror(self._t("mb_cannot_create_folder"), str(exc), parent=win)
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

        ttk.Button(btn_row, text=self._t("save"), command=_save
                   ).pack(side="left", padx=(0, 6))
        ttk.Button(btn_row, text=self._t("cancel_btn"), command=_cancel
                   ).pack(side="left")

        self._center_on_main(win)

    # ------------------------------------------------------------------
    # Settings field helpers
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Provider / model helpers
    # ------------------------------------------------------------------

