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
        """Apply the current color mode to all widgets.

        Parameters
        ----------
        reconfigure_tags:
            When False, skip the final ``_reconfigure_chat_tags()`` call.
            Pass False at startup when ``_apply_font_size()`` is called
            immediately afterwards — it already calls ``_reconfigure_chat_tags()``
            so the tags only need to be configured once.
        """
        mode = self._color_mode_var.get()
        c    = _THEME_COLORS.get(mode, _THEME_COLORS["light"])
        style = ttk.Style(self)

        if mode == "dark":
            style.theme_use("clam")
            # Base defaults propagate to all ttk widget types
            style.configure(".",
                background=c["window_bg"],
                foreground=c["text_fg"],
                fieldbackground=c["text_bg"],
                troughcolor=c["window_bg"],
                selectbackground=c["lb_sel_bg"],
                selectforeground=c["lb_sel_fg"],
                bordercolor="#555555",
                darkcolor="#1e1e1e",
                lightcolor="#3c3c3c",
            )
            style.configure("TFrame",       background=c["window_bg"])
            style.configure("TLabel",       background=c["window_bg"],
                                            foreground=c["text_fg"])
            style.configure("TLabelframe",  background=c["window_bg"],
                                            foreground=c["text_fg"])
            style.configure("TLabelframe.Label",
                            background=c["window_bg"], foreground=c["text_fg"])
            style.configure("TButton",
                background="#3c3c3c", foreground=c["text_fg"],
                relief="flat", borderwidth=1, padding=4,
            )
            style.map("TButton",
                background=[("active", "#505050"), ("pressed", "#404040")],
                foreground=[("active", c["text_fg"])],
            )
            style.configure("TEntry",
                fieldbackground=c["text_bg"],
                foreground=c["text_fg"],
                insertcolor=c["text_fg"],
            )
            style.configure("TCombobox",
                fieldbackground=c["text_bg"],
                foreground=c["text_fg"],
                background="#3c3c3c",
                selectbackground=c["lb_sel_bg"],
                selectforeground=c["lb_sel_fg"],
            )
            style.map("TCombobox",
                fieldbackground=[("readonly", c["text_bg"])],
                foreground=[("readonly", c["text_fg"])],
                selectbackground=[("readonly", c["lb_sel_bg"])],
            )
            style.configure("TScrollbar",
                background="#3c3c3c",
                troughcolor=c["window_bg"],
                arrowcolor=c["text_fg"],
            )
            style.configure("TSeparator", background="#555555")
            style.configure("TRadiobutton",
                background=c["window_bg"], foreground=c["text_fg"])
            style.map("TRadiobutton",
                background=[("active", c["window_bg"])],
                foreground=[("active", c["text_fg"])],
            )
            style.configure("TCheckbutton",
                background=c["window_bg"], foreground=c["text_fg"])
            # Window / paned sash
            self.configure(background=c["window_bg"])
            self._paned.configure(background=c["paned_bg"])
        else:
            # Restore the platform's native theme for light mode
            try:
                style.theme_use(self._default_ttk_theme)
            except tk.TclError:
                style.theme_use("default")
            try:
                self.configure(background=c["window_bg"])
            except Exception:
                pass
            self._paned.configure(background=c["paned_bg"])

        # Non-ttk widgets always need direct configuration
        try:
            self._chat_text.configure(
                bg=c["text_bg"], fg=c["text_fg"],
                insertbackground=c["text_fg"],
            )
        except Exception:
            pass
        try:
            self._input_text.configure(
                bg=c["input_bg"], fg=c["input_fg"],
                insertbackground=c["input_fg"],
            )
        except Exception:
            pass
        try:
            self._session_listbox.configure(
                bg=c["lb_bg"], fg=c["lb_fg"],
                selectbackground=c["lb_sel_bg"],
                selectforeground=c["lb_sel_fg"],
            )
        except Exception:
            pass
        if reconfigure_tags:
            self._reconfigure_chat_tags()

    def _reconfigure_chat_tags(self) -> None:
        """Re-apply chat-bubble colours for the current theme and font size."""
        c    = _THEME_COLORS.get(self._color_mode_var.get(), _THEME_COLORS["light"])
        size = self._font_size()
        try:
            self._chat_text.tag_configure(
                "user_label", foreground=c["user_fg"],
                font=("TkDefaultFont", size - 1, "bold"))
            self._chat_text.tag_configure(
                "user_body", foreground=c["user_fg"])
            self._chat_text.tag_configure(
                "assistant_label", foreground=c["assist_fg"],
                font=("TkDefaultFont", size - 1, "bold"))
            self._chat_text.tag_configure(
                "assistant_body", foreground=c["assist_body"])
            self._chat_text.tag_configure(
                "system_body", foreground=c["system_fg"],
                font=("TkDefaultFont", size - 1, "italic"))
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
        try:
            self._session_listbox.configure(font=("TkDefaultFont", max(size - 1, 9)))
        except Exception:
            pass
        # Secondary info labels: 1pt below body text, minimum 10pt
        _sub = max(size - 1, 10)
        try:
            self._session_status_lbl.configure(font=("TkDefaultFont", _sub))
        except Exception:
            pass
        try:
            self._busy_label.configure(font=("TkDefaultFont", _sub))
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

