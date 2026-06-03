"""Appearance, theming, and App Settings dialog methods."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, ttk

logger = logging.getLogger(__name__)

from uacragent.infra.persistence import (
    get_app_appearance, set_app_appearance,
    get_app_data_dir, set_app_data_dir,
    get_privacy_accepted, set_privacy_accepted,
)

from ._custom_widgets import _RoundedChip
from ._ui_constants import _STRINGS, _THEME_COLORS, _FONT_SIZE_VALUES, _icon_font_family


class AppearanceMixin:
    """Mixin: appearance, theming, language switching, and app-settings dialog."""

    @staticmethod
    def _runtime_secret_env_vars() -> tuple[str, ...]:
        """Return API-key env vars that must not be inherited by a relaunched process.

        Only genuine secrets (authentication credentials) belong here.
        Configuration settings such as EMBEDDING_PROVIDER and LOCAL_EMBEDDING_MODEL
        are NOT secrets — removing them from the child env would silently revert
        shell-level embedding settings after an app-data-folder relaunch.
        """
        return (
            "GOOGLE_API_KEY",
            "OPENAI_API_KEY",
            "DEEPSEEK_API_KEY",
        )

    def _clear_runtime_secrets(self) -> None:
        """Erase API-key/runtime-secret state from the current process."""
        for var in (self._gemini_key_var, self._openai_key_var, self._deepseek_key_var):
            try:
                var.set("")
            except Exception:  # noqa: BLE001
                pass
        for env_var in self._runtime_secret_env_vars():
            os.environ.pop(env_var, None)

    def _build_relaunch_command(self) -> list[str]:
        """Return the command used to relaunch the desktop app."""
        if getattr(sys, "frozen", False):
            return [sys.executable, *sys.argv[1:]]
        return [sys.executable, "-m", "uacragent.ui.desktop.app"]

    def _relaunch_after_app_data_change(self, old_app_data: Path) -> bool:
        """Relaunch the app and close the current process on success.

        Returns ``True`` when the new process was launched successfully.
        On failure, the app-data-folder change is rolled back and the current
        process remains open.
        """
        child_env = os.environ.copy()
        for env_var in self._runtime_secret_env_vars():
            child_env.pop(env_var, None)

        cmd = self._build_relaunch_command()
        try:
            subprocess.Popen(
                cmd,
                cwd=os.getcwd(),
                env=child_env,
                start_new_session=True,
            )
        except Exception as exc:  # noqa: BLE001
            set_app_data_dir(old_app_data)
            self._app_data_dir_var.set(str(old_app_data))
            self._show_info_dialog(
                self._t("app_data_relaunch_failed_title"),
                self._t("app_data_relaunch_failed_body").format(error=str(exc)),
            )
            return False

        self._clear_runtime_secrets()
        self.destroy()
        return True

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
            self._language_var.set(prefs.get("language",   "auto"))
        except Exception:  # noqa: BLE001
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
            except Exception as exc:  # noqa: BLE001
                logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
            self._paned.configure(background=c["window_bg"])

        # ── Non-ttk widgets need direct configuration ─────────────────
        # Message bubble canvas and frame backgrounds (individual bubble
        # widget colours are applied fresh on each _append_chat call)
        try:
            self._msg_canvas.configure(bg=c["text_bg"])
            self._msg_frame.configure(bg=c["text_bg"])
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # input_text colours are managed by _redraw_input_block_canvas below
        # CustomSessionList handles its own colours via update_colors()
        try:
            self._session_list.update_colors(c)
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # Sidebar sits on the window background — no card, just plain bg.
        _wbg = c["window_bg"]
        try:
            self._sidebar_frame.configure(bg=_wbg)
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # Chat pane outer frame also uses window_bg so the card margin shows.
        try:
            self._chat_frame.configure(bg=_wbg)
            self._hist_canvas.configure(bg=_wbg)
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # Chat top bar lives inside _hist_inner (the white card).
        # _top_bar_info_area is aliased to _chat_top_bar, so one call covers both.
        _card_bg = c["text_bg"]
        try:
            self._chat_top_bar.configure(bg=_card_bg)
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # Title and status labels are direct children of top_bar (stored refs).
        try:
            self._header_course_lbl.configure(
                bg=_card_bg, fg=c.get("text_fg", "#1a2744"))
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        try:
            self._session_status_lbl.configure(
                bg=_card_bg, fg=c.get("status_fg", "#6b7280"))
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # Sidebar toggle icon — parent_bg=text_bg since it lives inside the card
        try:
            self._toggle_sidebar_btn.update_colors(c, parent_bg=_card_bg)
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # Sidebar bottom separator (inside the rounded sidebar card)
        try:
            self._sidebar_sep.configure(bg=c.get("input_border", "#cdd4e8"))
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
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
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # App Settings chip
        try:
            self._gear_btn.update_style(
                chip_bg=_wbg,
                chip_fg=_fg,
                hover_bg=c.get("lb_hover_bg", "#dfe4f0"),
                parent_bg=_wbg,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # "Sessions" label and search bar
        try:
            self._sessions_label.configure(
                bg=_wbg, fg=c.get("status_fg", "#9aa5be"))
            self._search_outer.configure(bg=_wbg)
            self._redraw_search_cv()
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # Re-apply Session Settings visibility after theme colours are reset
        try:
            if self._sess_settings_visible:
                self._show_sess_settings()
            else:
                self._hide_sess_settings()
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # Flat chat canvas — re-sync size and bg
        try:
            self._redraw_hist_canvas()
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)

        # ── Overlay scrollbar (chat only; session list handles its own) ──
        # sb_bg is set to match text_bg in the theme so no track is visible
        _sb_col = c.get("sb_color", "#9aa5be")
        _sb_bg  = c.get("sb_bg", c["text_bg"])
        try:
            self._chat_vsb.update_style(_sb_col, _sb_bg)
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)

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
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # Reasoning mode chip (same visual style as effort chip)
        try:
            self._reasoning_chip.update_style(
                chip_bg=_act_bg, chip_fg=_inp_fg,
                hover_bg=_act_hov, parent_bg=_inp_bg,
                outline=_border,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # Session Settings (_RoundedChip)
        try:
            self._sess_settings_btn.update_style(
                chip_bg=_inp_bg, chip_fg=_inp_fg,
                hover_bg=_act_bg, parent_bg=_inp_bg,
                outline=_border,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # Send button (_RoundedChip, primary colours)
        _prim_bg  = c["btn_primary_bg"]
        _prim_fg  = c["btn_primary_fg"]
        _prim_hov = c.get("btn_primary_hover", "#e8961a")
        try:
            self._send_btn.update_style(
                chip_bg=_prim_bg, chip_fg=_prim_fg,
                hover_bg=_prim_hov, parent_bg=_inp_bg,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # Cancel button (_RoundedChip, red danger colours)
        _canc_bg  = c.get("btn_cancel_bg",    "#e53e3e")
        _canc_fg  = c.get("btn_cancel_fg",    "#ffffff")
        _canc_hov = c.get("btn_cancel_hover", "#c53030")
        try:
            self._cancel_btn.update_style(
                chip_bg=_canc_bg, chip_fg=_canc_fg,
                hover_bg=_canc_hov, parent_bg=_inp_bg,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # Search and upload tool buttons (_RoundedChip) — parent_bg must be
        # updated so the canvas background matches the input area in dark mode
        # and the "white edge" artifact (stale light-mode bg bleeding through)
        # does not appear.
        try:
            self._search_btn.update_style(
                chip_bg=_act_bg, chip_fg=_inp_fg,
                hover_bg=_act_hov, parent_bg=_inp_bg,
                outline=_border,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        try:
            self._upload_btn.update_style(
                chip_bg=_act_bg, chip_fg=_inp_fg,
                hover_bg=_act_hov, parent_bg=_inp_bg,
                outline=_border,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)

        # ── Rounded canvases ───────────────────────────────────────────
        # _redraw_hist_canvas() repaints the unified card rounded rect.
        try:
            self._redraw_list_canvas()
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        try:
            self._redraw_hist_canvas()
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        try:
            self._redraw_input_block_canvas()   # also calls _redraw_input_text_cv
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)

        # ── Search / upload button state after theme colours are reset ────────
        try:
            self._refresh_search_btn()
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        try:
            self._update_tool_btns()
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)

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
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)

    def _font_size(self) -> int:
        """Return the current font size as an integer."""
        return _FONT_SIZE_VALUES.get(self._font_size_var.get(), 13)

    def _apply_font_size(self) -> None:
        """Apply the selected font size to the named font and key widgets."""
        size = self._font_size()
        # Update the named default font — propagates to all ttk widgets
        try:
            tkfont.nametofont("TkDefaultFont").configure(size=size)
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)

        # ── Scale sidebar chip fonts ──────────────────────────────────────
        try:
            self._new_session_btn.update_style(font=("TkDefaultFont", size, "bold"))
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        try:
            self._gear_btn.update_style(
                font=("TkDefaultFont", size),
                icon_font=(_icon_font_family(), size + 4),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        try:
            self._sessions_label.configure(font=("TkDefaultFont", max(size - 2, 9)))
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        try:
            self._search_entry.configure(font=("TkDefaultFont", max(size - 1, 10)))
            self._redraw_search_cv()   # resize the entry window inside the canvas
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        try:
            # Session title: 1 pt larger than body for visual hierarchy
            self._header_course_lbl.configure(
                font=("TkDefaultFont", size + 1, "bold"))
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        try:
            # Quick-action label and chips scale with body font
            for _i, _c in enumerate(self._qa_chips):
                if _i == 0:
                    _c.configure(font=("TkDefaultFont", size))   # "Quick Actions:" label
                elif hasattr(_c, "update_style"):
                    _c.update_style(font=("TkDefaultFont", size))
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)

        # (Gear.TButton removed — App Settings is now a _RoundedChip updated above)
        # Widgets with explicit font tuples must be updated individually
        # (message bubbles use named-font references; new bubbles pick up size
        # automatically via _font_size() — existing bubbles retain creation size)
        try:
            self._input_text.configure(font=("TkDefaultFont", size))
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # Re-sync the input block height after the font size changes the text
        # widget's required height.  Schedule via after() so the widget has
        # time to recalculate its own geometry first.
        try:
            self.after(60, self._auto_resize_input)
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # Secondary info labels: 1pt below body text, minimum 10pt
        _sub = max(size - 1, 10)
        try:
            self._session_status_lbl.configure(font=("TkDefaultFont", _sub))
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
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
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # Reasoning mode chip (same control size as effort chip)
        try:
            self._reasoning_chip.update_style(font=("TkDefaultFont", _ctrl_size))
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # Session Settings (_RoundedChip)
        try:
            self._sess_settings_btn.update_style(
                font=("TkDefaultFont", _ctrl_size),
                icon_font=(_icon_font_family(), _ctrl_size + 4),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # Send button (_RoundedChip)
        try:
            self._send_btn.update_style(font=("TkDefaultFont", _ctrl_size, "bold"))
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # Cancel button (_RoundedChip) — same bold style as Send
        try:
            self._cancel_btn.update_style(font=("TkDefaultFont", _ctrl_size, "bold"))
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # Search and upload icon buttons
        try:
            for _btn in (self._search_btn, self._upload_btn):
                _btn.update_style(font=("TkDefaultFont", max(_ctrl_size, 12)))
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # Tooltip font size — slightly smaller than body text, floor at 9
        try:
            _tip_size = max(size - 4, 9)
            self._search_tooltip.update_font_size(_tip_size)
            self._upload_tooltip.update_font_size(_tip_size)
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: tooltip font size update failed: %s", exc)
        # Tooltip colours
        try:
            _tip_bg = c.get("tooltip_bg", "#1a2744")
            _tip_fg = c.get("tooltip_fg", "#ffffff")
            self._search_tooltip.update_style(_tip_bg, _tip_fg)
            self._upload_tooltip.update_style(_tip_bg, _tip_fg)
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: tooltip style update failed: %s", exc)
        # Session list items carry explicit font tuples so the named-font
        # update above does not reach them — propagate the new size explicitly.
        try:
            self._session_list.update_font(size)
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # Placeholder label (shown when no session is active)
        try:
            self._ph_lbl.configure(font=("TkDefaultFont", size + 1))
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # Drag-and-drop overlay label
        try:
            self._dnd_overlay_lbl.configure(font=("TkDefaultFont", size + 5, "bold"))
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)

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
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # Reasoning chip text also uses localised mode names
        try:
            self._reasoning_chip.set_text(self._reasoning_chip_text())
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # Update the ⋯ popup menu labels in the session list
        try:
            self._session_list.set_menu_labels(
                self._t("rename"), self._t("delete")
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_theme: widget not ready or update failed: %s", exc)
        # Tooltip texts
        try:
            self._search_tooltip.update_text(self._t("tooltip_web_search"))
            self._upload_tooltip.update_text(self._t("tooltip_attach"))
        except Exception as exc:  # noqa: BLE001
            logger.debug("_apply_language: tooltip text update failed: %s", exc)

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

        # Snapshot current values so Cancel can revert all changes.
        _saved_color = self._color_mode_var.get()
        _saved_font  = self._font_size_var.get()
        _saved_lang  = self._language_var.get()
        _saved_store = self._openai_store_var.get()

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
        for _val, _display in [("auto", "Auto"), ("en", "English"), ("zh_CN", "中文（简体）")]:
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
                title=self._t("app_data_browse_title"),
                initialdir=path_var.get() or str(Path.home()),
            )
            if folder:
                path_var.set(folder)

        _browse_chip = _RoundedChip(
            frm, text=self._t("app_data_browse_btn"),
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

        # ── Privacy section ──────────────────────────────────────────
        tk.Frame(frm, bg=_border, height=1).grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=(14, 12))
        row += 1

        tk.Label(frm, text=self._t("privacy_section"),
                 bg=_cbg, fg=_fg,
                 font=("TkDefaultFont", _sz, "bold"),
                 anchor="w").grid(row=row, column=0, columnspan=3,
                                  sticky="w", pady=(0, 6))
        row += 1

        _privacy_link = tk.Label(
            frm, text=self._t("privacy_view_btn"),
            bg=_cbg, fg=c.get("link_fg", "#1b3167"),
            font=("TkDefaultFont", _sz, "underline"),
            cursor="hand2", anchor="w",
        )
        _privacy_link.grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 10))
        _privacy_link.bind("<Button-1>", lambda _e: self._show_privacy_dialog())
        row += 1

        # ── Provider data storage subsection ─────────────────────────
        tk.Label(frm, text=self._t("provider_data_section"),
                 bg=_cbg, fg=_fg,
                 font=("TkDefaultFont", _sz, "bold"),
                 anchor="w").grid(row=row, column=0, columnspan=3,
                                  sticky="w", pady=(0, 6))
        row += 1

        # OpenAI — programmatic opt-out via store=false
        _openai_cb = tk.Checkbutton(
            frm,
            text=self._t("openai_store_label"),
            variable=self._openai_store_var,
            bg=_cbg, fg=_fg,
            activebackground=_cbg, activeforeground=_fg,
            selectcolor=_cbg,
            relief="flat", bd=0, highlightthickness=0,
            font=("TkDefaultFont", _sz),
            anchor="w",
        )
        _openai_cb.grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 2))
        row += 1
        tk.Label(frm, text=self._t("openai_store_hint"),
                 bg=_cbg, fg=_sfg,
                 font=("TkDefaultFont", _nsz),
                 justify="left", anchor="w",
                 wraplength=420,
                 ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 10))
        row += 1

        # Gemini — informational only
        tk.Label(frm, text=self._t("gemini_store_hint"),
                 bg=_cbg, fg=_sfg,
                 font=("TkDefaultFont", _nsz),
                 justify="left", anchor="w",
                 wraplength=420,
                 ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 6))
        row += 1

        # DeepSeek — informational only
        tk.Label(frm, text=self._t("deepseek_store_hint"),
                 bg=_cbg, fg=_sfg,
                 font=("TkDefaultFont", _nsz),
                 justify="left", anchor="w",
                 wraplength=420,
                 ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 4))
        row += 1

        # Separator before buttons
        tk.Frame(frm, bg=_border, height=1).grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=(8, 12))
        row += 1

        # ── Buttons ───────────────────────────────────────────────────
        btn_row = tk.Frame(frm, bg=_cbg)
        btn_row.grid(row=row, column=0, columnspan=3, sticky="e")

        def _save() -> None:
            # ── 1. Appearance settings (always applied on Save) ──────────────
            set_app_appearance(
                self._color_mode_var.get(),
                self._font_size_var.get(),
                self._language_var.get(),
            )
            # Apply language now (was deferred to avoid mid-dialog churn)
            self._apply_language()

            # ── 2. Provider privacy settings ──────────────────────────────────
            # Updating os.environ alone is not enough — the cached LLM client
            # was built with the old store= value.  Nulling _agent forces a
            # fresh client construction on the next request.
            from uacragent.infra.persistence import set_provider_privacy, is_safe_app_data_target  # noqa: PLC0415
            import os as _os
            _store = self._openai_store_var.get()
            set_provider_privacy(openai_store_responses=_store)
            _os.environ["OPENAI_STORE_RESPONSES"] = "true" if _store else "false"
            if hasattr(self, "_agent"):
                self._agent = None

            # ── 3. App data folder change ─────────────────────────────────────
            # All filesystem work (folder creation, relaunch) happens ONLY after
            # the user explicitly confirms.  Cancelling at any point leaves the
            # filesystem unchanged — no unmanaged empty folders are created.
            chosen = path_var.get().strip()
            if not chosen:
                win.destroy()
                return

            p = Path(chosen)
            current_app_data = get_app_data_dir().resolve()
            new_app_data = p.resolve()

            if new_app_data == current_app_data:
                # Path unchanged — close dialog, nothing else to do.
                win.destroy()
                return

            # ── 3a. Safety check: block non-empty foreign folders ─────────────
            # A non-empty folder that has never been used as UACRAgent app data
            # risks file-name collisions (index.json, logs/, models/, etc.).
            # This is a hard block, not just a warning, so the user cannot
            # accidentally overwrite their own files.
            if not is_safe_app_data_target(new_app_data):
                self._show_info_dialog(
                    self._t("app_data_nonempty_title"),
                    self._t("app_data_nonempty_body").format(path=new_app_data),
                )
                return   # dialog stays open; filesystem unchanged ✓

            # ── 3b. Confirmation dialog ───────────────────────────────────────
            # Shown BEFORE any filesystem operation so cancelling is a clean
            # no-op.  The folder is created only if the user clicks "Change".
            if not self._show_confirm_dialog(
                self._t("app_data_change_title"),
                self._t("app_data_change_body").format(path=new_app_data),
                confirm_text=self._t("app_data_change_confirm"),
            ):
                return   # cancelled — filesystem unchanged ✓

            # ── 3c. Create the folder (only after confirmation) ───────────────
            try:
                new_app_data.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                self._show_info_dialog(self._t("mb_cannot_create_folder"), str(exc))
                return

            # ── 3d. Save the current session before the relaunch ─────────────
            if not self._save_current_session():
                self._show_info_dialog(
                    self._t("mb_session_not_saved_title"),
                    self._t("mb_session_not_saved_body"),
                )

            # ── 3e. Persist the new path and relaunch ─────────────────────────
            set_app_data_dir(p)           # also writes uacragent_appdata.json
            self._app_data_dir_var.set(str(new_app_data))
            win.destroy()
            self._relaunch_after_app_data_change(current_app_data)

        def _cancel() -> None:
            # Revert all changes — appearance live-previews and the
            # privacy checkbox which is not live but must also be rolled back.
            self._color_mode_var.set(_saved_color)
            self._font_size_var.set(_saved_font)
            self._language_var.set(_saved_lang)
            self._openai_store_var.set(_saved_store)
            self._apply_theme()
            self._apply_font_size()
            self._safe_destroy_toplevel(win)

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

        # Wire the OS-level window-close button (×) to _cancel so that live-
        # preview appearance changes are reverted before the window is destroyed,
        # and so _safe_destroy_toplevel guards against TclError on teardown.
        win.protocol("WM_DELETE_WINDOW", _cancel)
        self._center_on_main(win)

    # ------------------------------------------------------------------
    # Privacy notice dialogs
    # ------------------------------------------------------------------

    def _show_modal(
        self,
        win: tk.Toplevel,
        *,
        on_close: "callable | None" = None,
        wait: bool = True,
    ) -> None:
        """Position *win* centred on the main window, make it modal, then wait.

        Unlike ``_center_on_main`` (which defers positioning via ``after_idle``),
        this helper centres synchronously so that ``grab_set()`` is always called
        **after** ``deiconify()`` — the only reliable order on all platforms,
        including macOS where a grab on a withdrawn/invisible window silently
        does nothing.

        Parameters
        ----------
        win:
            A ``tk.Toplevel`` that has already been populated with widgets.
            It must have been withdrawn before this call (``_make_toplevel``
            does this automatically).
        on_close:
            Optional callable wired to ``WM_DELETE_WINDOW``.  When omitted
            the protocol is left at the default (destroy the window).
        wait:
            When ``True`` (default) block until the window is destroyed.
        """
        # Flush layout so winfo_req* returns the real dimensions.
        win.update_idletasks()
        dw = win.winfo_reqwidth()  or 440
        dh = win.winfo_reqheight() or 300
        mw = self.winfo_width()
        mh = self.winfo_height()
        mx = self.winfo_rootx()
        my = self.winfo_rooty()
        x  = mx + (mw - dw) // 2
        y  = my + (mh - dh) // 2
        win.geometry(f"+{x}+{y}")

        if on_close is not None:
            win.protocol("WM_DELETE_WINDOW", on_close)

        win.deiconify()          # make viewable FIRST …
        win.lift()
        win.focus_force()
        win.grab_set()           # … then grab so it actually takes effect

        # _make_toplevel() sets alpha=0 on macOS to suppress the OS-default
        # placement flash.  Restore it now that the window is positioned.
        import sys as _sys
        if _sys.platform == "darwin":
            try:
                win.wm_attributes("-alpha", 1.0)
            except tk.TclError:
                pass

        if wait:
            win.wait_window()

    def _show_privacy_dialog(self) -> None:
        """Show the privacy notice dialog (always a blocking modal).

        Behaviour is identical whether triggered on first launch or from the
        App Settings "View Privacy Notice" link:

        * [Accept] — persists ``privacy_notice_accepted = true`` and closes.
        * [Reject] — clears any previous acceptance (sets ``false``), then
          opens the secondary rejection dialog where the user must either go
          back and accept or quit the application.
        * Window-close (×) — treated the same as Reject.
        """
        c      = self._themed_colors()
        _wbg   = c["window_bg"]
        _cbg   = c.get("text_bg", "#ffffff")
        _fg    = c["text_fg"]
        _pbg   = c["btn_primary_bg"]
        _pfg   = c["btn_primary_fg"]
        _phov  = c.get("btn_primary_hover", _pbg)
        _brd   = c.get("input_border", "#cdd4e8")
        _sz    = self._font_size() if hasattr(self, "_font_size") else 13

        win = self._make_toplevel()
        win.title(self._t("privacy_notice_title"))
        win.configure(bg=_wbg)
        win.resizable(False, False)

        # Outer padding → inner card
        outer = tk.Frame(win, bg=_wbg, padx=12, pady=12)
        outer.pack(fill="both", expand=True)

        frm = tk.Frame(outer, bg=_cbg, padx=20, pady=18,
                       highlightthickness=1, highlightbackground=_brd)
        frm.pack(fill="both", expand=True)

        tk.Label(
            frm, text=self._t("privacy_notice_body"),
            bg=_cbg, fg=_fg,
            font=("TkDefaultFont", _sz),
            justify="left", anchor="w", wraplength=400,
        ).pack(anchor="w", pady=(0, 20))

        btn_row = tk.Frame(frm, bg=_cbg)
        btn_row.pack(anchor="e")

        from ._custom_widgets import _RoundedChip

        def _on_accept() -> None:
            set_privacy_accepted(True)
            win.destroy()

        def _on_reject() -> None:
            # Clear any previously stored acceptance so the app cannot be used
            # without going back and accepting or quitting.
            set_privacy_accepted(False)
            win.destroy()
            self._show_privacy_rejected_dialog()

        _RoundedChip(
            btn_row, text=self._t("privacy_accept"),
            chip_bg=_pbg, chip_fg=_pfg,
            parent_bg=_cbg,
            font=("TkDefaultFont", _sz, "bold"),
            padx=14, pady=6,
            hover_bg=_phov,
            command=_on_accept,
        ).pack(side="left", padx=(0, 8))

        _reject_bg  = c.get("btn_cancel_bg",    "#e53e3e")
        _reject_fg  = c.get("btn_cancel_fg",    "#ffffff")
        _reject_hov = c.get("btn_cancel_hover", "#c53030")
        _RoundedChip(
            btn_row, text=self._t("privacy_reject"),
            chip_bg=_reject_bg, chip_fg=_reject_fg,
            parent_bg=_cbg,
            font=("TkDefaultFont", _sz),
            padx=14, pady=6,
            hover_bg=_reject_hov,
            command=_on_reject,
        ).pack(side="left")

        # Always a blocking modal — grab_set after deiconify (reliable on all platforms).
        self._show_modal(win, on_close=_on_reject, wait=True)

    def _show_privacy_rejected_dialog(self) -> None:
        """Secondary dialog shown when the user rejects the privacy notice.

        [Go Back]  → close this dialog and re-open the privacy notice.
        [Quit]     → destroy the main application window.
        """
        c      = self._themed_colors()
        _wbg   = c["window_bg"]
        _cbg   = c.get("text_bg", "#ffffff")
        _fg    = c["text_fg"]
        _pbg   = c["btn_primary_bg"]
        _pfg   = c["btn_primary_fg"]
        _phov  = c.get("btn_primary_hover", _pbg)
        _brd   = c.get("input_border", "#cdd4e8")
        _sz    = self._font_size() if hasattr(self, "_font_size") else 13

        win = self._make_toplevel()
        win.title(self._t("privacy_rejected_title"))
        win.configure(bg=_wbg)
        win.resizable(False, False)

        outer = tk.Frame(win, bg=_wbg, padx=12, pady=12)
        outer.pack(fill="both", expand=True)

        frm = tk.Frame(outer, bg=_cbg, padx=20, pady=18,
                       highlightthickness=1, highlightbackground=_brd)
        frm.pack(fill="both", expand=True)

        tk.Label(
            frm, text=self._t("privacy_rejected_body"),
            bg=_cbg, fg=_fg,
            font=("TkDefaultFont", _sz),
            justify="left", anchor="w", wraplength=380,
        ).pack(anchor="w", pady=(0, 20))

        btn_row = tk.Frame(frm, bg=_cbg)
        btn_row.pack(anchor="e")

        from ._custom_widgets import _RoundedChip

        def _go_back() -> None:
            win.destroy()
            self._show_privacy_dialog()

        def _quit() -> None:
            win.destroy()
            self.destroy()

        _RoundedChip(
            btn_row, text=self._t("privacy_go_back"),
            chip_bg=_pbg, chip_fg=_pfg,
            parent_bg=_cbg,
            font=("TkDefaultFont", _sz, "bold"),
            padx=14, pady=6,
            hover_bg=_phov,
            command=_go_back,
        ).pack(side="left", padx=(0, 8))

        _quit_bg  = c.get("btn_cancel_bg",    "#e53e3e")
        _quit_fg  = c.get("btn_cancel_fg",    "#ffffff")
        _quit_hov = c.get("btn_cancel_hover", "#c53030")
        _RoundedChip(
            btn_row, text=self._t("privacy_quit"),
            chip_bg=_quit_bg, chip_fg=_quit_fg,
            parent_bg=_cbg,
            font=("TkDefaultFont", _sz),
            padx=14, pady=6,
            hover_bg=_quit_hov,
            command=_quit,
        ).pack(side="left")

        # Closing the window (× button) is the same as quitting.
        self._show_modal(win, on_close=_quit, wait=True)

    def _check_privacy_consent(self) -> None:
        """Show the privacy notice on first launch if not yet accepted."""
        if not get_privacy_accepted():
            self._show_privacy_dialog()

    # ------------------------------------------------------------------
    # Settings field helpers
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Provider / model helpers
    # ------------------------------------------------------------------
