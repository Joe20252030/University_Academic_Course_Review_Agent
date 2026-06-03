"""Session Settings dialog methods."""
from __future__ import annotations

import os
import re
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

from uacragent.domain.providers import (
    PROVIDER_IDS, get_provider, env_var_for, models_for,
)
from uacragent.domain.types import DocumentType, ExamFormat, ExamType, ExportFormat
from uacragent.infra.persistence import get_app_data_dir
from uacragent.infra.workspace import workspace_paths

from ._custom_widgets import AutoHideScrollbar, _RoundedChip, draw_rounded_rect
from ._ui_constants import (
    _PAD, _SUPPORTED_FILETYPES, _STRINGS, _THEME_COLORS, _FONT_SIZE_VALUES,
    _open_in_os, _open_file_in_os, _open_folder_in_os,
)


class SettingsMixin:
    """Mixin: session settings dialog — open, apply, and all helper methods."""

    @staticmethod
    def _safe_destroy_toplevel(win: tk.Toplevel | tk.Tk | None) -> None:
        """Best-effort ``destroy()`` wrapper for dialog callbacks.

        On newer Tk / Python combinations, a button or WM_DELETE callback can
        race with Tcl's own widget-command teardown and raise
        ``TclError: can't delete Tcl command`` when ``destroy()`` is invoked a
        second time through a stale bound method.  Treat that path as an
        already-closed dialog and swallow it.
        """
        if win is None:
            return
        try:
            if not win.winfo_exists():
                return
        except Exception:
            return
        try:
            win.destroy()
        except tk.TclError as exc:
            if "can't delete Tcl command" not in str(exc):
                raise

    @staticmethod
    def _is_managed_exam_info_path(path: str, workspace_folder: Path | None) -> bool:
        """Return True when *path* is inside the workspace-managed exam-info area."""
        if not path or workspace_folder is None:
            return False
        try:
            p = Path(path).resolve()
            exam_root = (
                Path(workspace_folder).resolve() / ".uacragent" / "uploads" / "exam_info"
            )
            p.relative_to(exam_root)
            return True
        except Exception:
            return False

    def _cleanup_stale_exam_info_copy(
        self,
        old_path: str,
        new_path: str,
        workspace_folder: Path | None,
    ) -> None:
        """Delete a superseded workspace-local exam-info copy, if any.

        Only files inside ``<workspace>/.uacragent/uploads/exam_info/`` are
        eligible. User-owned source files outside the workspace are never
        touched.
        """
        if not old_path or old_path == new_path:
            return
        if not self._is_managed_exam_info_path(old_path, workspace_folder):
            return
        try:
            stale = Path(old_path)
            if stale.exists():
                stale.unlink()
            parent = stale.parent
            if parent.name == "exam_info" and parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
        except Exception:
            # Best-effort cleanup only — never block Apply on a stale-file delete.
            pass

    @classmethod
    def _available_local_embedding_models(cls) -> dict[str, str]:
        """Return the local embedding choices valid for the current runtime."""
        if getattr(sys, "frozen", False):
            return {
                "all-MiniLM-L6-v2  ★ recommended  (~80 MB, ONNX)": "all-MiniLM-L6-v2",
            }
        return cls._FREE_EMB_MODELS

    @classmethod
    def _normalize_local_embedding_model(cls, model_name: str) -> str:
        """Return a valid local embedding model id for persisted/session state."""
        available = set(cls._available_local_embedding_models().values())
        return model_name if model_name in available else "all-MiniLM-L6-v2"

    @classmethod
    def _local_model_display_label(cls, model_name: str) -> str:
        """Return the current-runtime display label for a local embedding model."""
        for display, internal in cls._available_local_embedding_models().items():
            if internal == model_name:
                return display
        return model_name

    def _register_settings_wrap_target(
        self,
        widget: tk.Widget,
        container: tk.Widget | None = None,
        *,
        pad: int = 24,
        min_wrap: int = 180,
    ) -> None:
        """Register a settings-dialog label whose wraplength should resize live."""
        if not hasattr(self, "_settings_wrap_targets"):
            self._settings_wrap_targets: list[tuple[tk.Widget, tk.Widget, int, int]] = []
        self._settings_wrap_targets.append((widget, container or widget, pad, min_wrap))
        self._refresh_settings_wrap_targets()

    def _refresh_settings_wrap_targets(self) -> None:
        """Recompute wraplengths for settings-dialog notice labels."""
        targets = getattr(self, "_settings_wrap_targets", None)
        if not targets:
            return
        # Cancel any queued debounced call before we run synchronously so the
        # same refresh does not fire twice (once now, once from after()).
        _pending = getattr(self, "_settings_wrap_after_id", None)
        if _pending is not None:
            try:
                self.after_cancel(_pending)
            except Exception:
                pass
        self._settings_wrap_after_id = None
        kept: list[tuple[tk.Widget, tk.Widget, int, int]] = []
        for widget, container, pad, min_wrap in targets:
            try:
                if not widget.winfo_exists() or not container.winfo_exists():
                    continue
                width = max(min_wrap, container.winfo_width() - pad)
                current = int(float(widget.cget("wraplength") or 0))
                if current != width:
                    widget.configure(wraplength=width)
                kept.append((widget, container, pad, min_wrap))
            except tk.TclError:
                continue
        self._settings_wrap_targets = kept

    def _schedule_settings_wrap_refresh(self, delay_ms: int = 30) -> None:
        """Throttle settings-dialog wrap recalculation during live resize.

        Coalesces bursts of ``<Configure>`` events into at most one pending
        refresh at a time. This keeps resize dragging smooth while still
        allowing notice labels to reflow continuously as the user drags.
        """
        win = getattr(self, "_settings_win", None)
        if win is None or not win.winfo_exists():
            return
        _after_id = getattr(self, "_settings_wrap_after_id", None)
        if _after_id is not None:
            return
        try:
            self._settings_wrap_after_id = win.after(
                delay_ms, self._refresh_settings_wrap_targets
            )
        except tk.TclError:
            self._settings_wrap_after_id = None

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

    # Source-install local model labels shown in the Settings dialog.
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

    def _make_toplevel(self) -> tk.Toplevel:
        """Create a Toplevel that is invisible from the very first frame.

        On macOS the window server can paint a Toplevel at the OS-default
        position before Python's next line executes.  Setting ``alpha=0``
        as the *very first* operation (even before ``withdraw``) eliminates
        that one-frame flash on every platform where the attribute is
        supported.  ``_center_on_main`` restores ``alpha=1`` after positioning.
        """
        win = tk.Toplevel(self)
        if sys.platform == "darwin":
            try:
                win.wm_attributes("-alpha", 0.0)
            except tk.TclError:
                pass
        win.withdraw()
        return win

    def _center_on_main(self, win: tk.Toplevel) -> None:
        """Position *win* at the centre of the main application window.

        Immediately withdraws the window (so it is invisible), then on the
        next idle tick flushes geometry, computes the centred position, moves
        the window there, and finally shows it with deiconify.  This prevents
        the brief flash where tkinter first renders the dialog at a random
        OS-chosen position before moving it.

        Note: screen coordinates are intentionally *not* clamped to ≥ 0.
        On multi-monitor setups, monitors to the left or above the primary
        display have negative x/y coordinates, and clamping to 0 would
        incorrectly snap the dialog to the primary monitor instead.
        """
        # NOTE: callers must call  win.withdraw()  immediately after creating
        # the Toplevel (before adding any widgets) so the window never appears
        # at the OS-chosen default position.  This function only positions
        # and reveals the already-hidden window.

        # macOS: set alpha=0 NOW (before after_idle) so the window is
        # invisible during widget layout.  On first open winfo_reqwidth()
        # returns 0 until update_idletasks() runs inside _do_center, and
        # the OS can briefly expose the window at the wrong position while
        # that computation happens.  Being transparent from the start
        # eliminates that one-frame flash entirely.
        _alpha_set = False
        if sys.platform == "darwin":
            try:
                win.wm_attributes("-alpha", 0.0)
                _alpha_set = True
            except tk.TclError:
                pass

        def _do_center() -> None:
            try:
                # Flush pending layout so winfo_req* returns accurate sizes.
                # Safe to call now because the window is fully transparent.
                win.update_idletasks()
                dw = win.winfo_reqwidth()  or win.winfo_width()  or 420
                dh = win.winfo_reqheight() or win.winfo_height() or 280
                mw = self.winfo_width()
                mh = self.winfo_height()
                mx = self.winfo_rootx()
                my = self.winfo_rooty()
                x = mx + (mw - dw) // 2
                y = my + (mh - dh) // 2
                win.geometry(f"+{x}+{y}")
            except tk.TclError:
                return
            try:
                win.deiconify()
            except tk.TclError:
                return
            if _alpha_set:
                def _restore() -> None:
                    try:
                        win.wm_attributes("-alpha", 1.0)
                    except tk.TclError:
                        pass
                win.after(30, _restore)

        win.after_idle(_do_center)

    # ── Themed dialog helpers ──────────────────────────────────────────────

    def _themed_colors(self) -> dict:
        """Return the active theme color dict."""
        mode = getattr(self, "_color_mode_var", None)
        key  = mode.get() if mode else "light"
        return _THEME_COLORS.get(key, _THEME_COLORS["light"])

    def _show_info_dialog(self, title: str, message: str) -> None:
        """Show a themed information dialog (replaces messagebox.showinfo)."""
        c     = self._themed_colors()
        _wbg  = c["window_bg"]
        _cbg  = c.get("text_bg", "#ffffff")      # card fill
        _fg   = c["text_fg"]
        _pbg  = c["btn_primary_bg"]
        _pfg  = c["btn_primary_fg"]
        _phov = c.get("btn_primary_hover", _pbg)
        _brd  = c.get("input_border", "#cdd4e8")
        _sz   = self._font_size() if hasattr(self, "_font_size") else 13

        win = self._make_toplevel()
        win.title(title)
        win.configure(bg=_wbg)
        win.resizable(False, False)
        win.grab_set()

        # Outer padding frame (window_bg) → inner card (text_bg)
        outer = tk.Frame(win, bg=_wbg, padx=12, pady=12)
        outer.pack(fill="both", expand=True)

        frm = tk.Frame(outer, bg=_cbg, padx=20, pady=18,
                       highlightthickness=1, highlightbackground=_brd)
        frm.pack(fill="both", expand=True)

        tk.Label(
            frm, text=message,
            bg=_cbg, fg=_fg,
            font=("TkDefaultFont", _sz),
            justify="left", anchor="w", wraplength=360,
        ).pack(anchor="w", pady=(0, 16))

        btn_row = tk.Frame(frm, bg=_cbg)
        btn_row.pack(anchor="e")
        _RoundedChip(
            btn_row, text=self._t("btn_ok"),
            chip_bg=_pbg, chip_fg=_pfg,
            parent_bg=_cbg,
            font=("TkDefaultFont", _sz, "bold"),
            padx=14, pady=6,
            hover_bg=_phov,
            command=lambda: self._safe_destroy_toplevel(win),
        ).pack()

        self._center_on_main(win)
        win.wait_window()

    def _show_confirm_dialog(
        self,
        title: str,
        message: str,
        confirm_text: str | None = None,
        destructive: bool = False,
    ) -> bool:
        """Show a themed yes/no dialog. Returns True if confirmed."""
        c        = self._themed_colors()
        _wbg     = c["window_bg"]
        _cbg     = c.get("text_bg", "#ffffff")    # card fill
        _fg      = c["text_fg"]
        _sz      = self._font_size() if hasattr(self, "_font_size") else 13
        _border  = c["input_border"]
        _pbg     = c["btn_primary_bg"]
        _pfg     = c["btn_primary_fg"]
        _phov    = c.get("btn_primary_hover", _pbg)
        if destructive:
            _cfm_bg  = c.get("btn_cancel_bg",    "#e53e3e")
            _cfm_fg  = c.get("btn_cancel_fg",    "#ffffff")
            _cfm_hov = c.get("btn_cancel_hover", "#c53030")
        else:
            _cfm_bg  = _pbg
            _cfm_fg  = _pfg
            _cfm_hov = _phov

        result: list[bool] = [False]

        win = self._make_toplevel()
        win.title(title)
        win.configure(bg=_wbg)
        win.resizable(False, False)
        win.grab_set()

        # Outer padding frame (window_bg) → inner card (text_bg)
        outer = tk.Frame(win, bg=_wbg, padx=12, pady=12)
        outer.pack(fill="both", expand=True)

        frm = tk.Frame(outer, bg=_cbg, padx=20, pady=18,
                       highlightthickness=1, highlightbackground=_border)
        frm.pack(fill="both", expand=True)

        tk.Label(
            frm, text=message,
            bg=_cbg, fg=_fg,
            font=("TkDefaultFont", _sz),
            justify="left", anchor="w", wraplength=400,
        ).pack(anchor="w", pady=(0, 20))

        btn_row = tk.Frame(frm, bg=_cbg)
        btn_row.pack(anchor="e")

        def _ok():
            result[0] = True
            self._safe_destroy_toplevel(win)

        def _cancel():
            self._safe_destroy_toplevel(win)

        _RoundedChip(
            btn_row,
            text=confirm_text or self._t("btn_ok"),
            chip_bg=_cfm_bg, chip_fg=_cfm_fg,
            parent_bg=_cbg,
            font=("TkDefaultFont", _sz, "bold"),
            padx=14, pady=6,
            hover_bg=_cfm_hov,
            command=_ok,
        ).pack(side="left", padx=(0, 10))

        _RoundedChip(
            btn_row, text=self._t("cancel_btn"),
            chip_bg=_cbg, chip_fg=_fg,
            parent_bg=_cbg,
            font=("TkDefaultFont", _sz),
            padx=14, pady=6,
            outline=_border, outline_width=1,
            hover_bg=c.get("qa_bg", "#edf0f8"),
            command=_cancel,
        ).pack(side="left")

        win.protocol("WM_DELETE_WINDOW", _cancel)
        self._center_on_main(win)
        win.wait_window()
        return result[0]

    def _show_rename_dialog(
        self,
        title: str,
        prompt: str,
        initial: str = "",
    ) -> str | None:
        """Show a themed string-input dialog. Returns the string or None if cancelled."""
        c       = self._themed_colors()
        _wbg    = c["window_bg"]
        _cbg    = c.get("text_bg", "#ffffff")     # card fill
        _fg     = c["text_fg"]
        _ibg    = c["input_bg"]
        _ifg    = c["input_fg"]
        _border = c["input_border"]
        _pbg    = c["btn_primary_bg"]
        _pfg    = c["btn_primary_fg"]
        _phov   = c.get("btn_primary_hover", _pbg)
        _sz     = self._font_size() if hasattr(self, "_font_size") else 13

        result: list[str | None] = [None]

        win = self._make_toplevel()
        win.title(title)
        win.configure(bg=_wbg)
        win.resizable(False, False)
        win.grab_set()

        # Outer padding frame (window_bg) → inner card (text_bg)
        outer = tk.Frame(win, bg=_wbg, padx=12, pady=12)
        outer.pack(fill="both", expand=True)

        frm = tk.Frame(outer, bg=_cbg, padx=20, pady=18,
                       highlightthickness=1, highlightbackground=_border)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(0, weight=1)

        tk.Label(
            frm, text=prompt,
            bg=_cbg, fg=_fg,
            font=("TkDefaultFont", _sz),
            anchor="w",
        ).pack(anchor="w", pady=(0, 8))

        entry_var = tk.StringVar(value=initial)
        entry = tk.Entry(
            frm, textvariable=entry_var,
            bg=_ibg, fg=_ifg,
            insertbackground=_ifg,
            relief="flat", bd=0,
            font=("TkDefaultFont", _sz),
            highlightthickness=1,
            highlightbackground=_border,
            highlightcolor=_pbg,
        )
        entry.pack(fill="x", ipady=4, pady=(0, 16))
        entry.focus_set()
        entry.select_range(0, "end")

        btn_row = tk.Frame(frm, bg=_cbg)
        btn_row.pack(anchor="e")

        def _ok(_event=None):
            val = entry_var.get().strip()
            if val:
                result[0] = val
            self._safe_destroy_toplevel(win)

        def _cancel(_event=None):
            self._safe_destroy_toplevel(win)

        _RoundedChip(
            btn_row, text=self._t("settings_apply_btn"),
            chip_bg=_pbg, chip_fg=_pfg,
            parent_bg=_cbg,
            font=("TkDefaultFont", _sz, "bold"),
            padx=14, pady=6,
            hover_bg=_phov,
            command=_ok,
        ).pack(side="left", padx=(0, 10))

        _RoundedChip(
            btn_row, text=self._t("cancel_btn"),
            chip_bg=_cbg, chip_fg=_fg,
            parent_bg=_cbg,
            font=("TkDefaultFont", _sz),
            padx=14, pady=6,
            outline=_border, outline_width=1,
            hover_bg=c.get("qa_bg", "#edf0f8"),
            command=_cancel,
        ).pack(side="left")

        entry.bind("<Return>", _ok)
        entry.bind("<Escape>", _cancel)
        win.protocol("WM_DELETE_WINDOW", _cancel)
        self._center_on_main(win)
        win.wait_window()
        return result[0]

    def _make_section_card(
        self,
        parent: tk.Widget,
        row: int,
        title: str,
        c: dict,
    ) -> tk.Frame:
        """Build a rounded-border section card, grid it into *parent* at *row*.

        Returns the inner content ``tk.Frame`` (populate it with grid or pack
        as normal).  A ``draw_rounded_rect`` outline is drawn on a canvas that
        backs the card; it redraws whenever the card is resized.

        The default column layout of the returned frame is ``columnconfigure(1,
        weight=1)`` — a two-column label+widget setup that matches the majority
        of settings sections.  Override with another ``columnconfigure`` call
        on the returned frame when needed.
        """
        _wbg  = c["window_bg"]
        _cbg  = c.get("text_bg", "#ffffff")   # white card fill
        _fg   = c["text_fg"]
        _brd  = c["input_border"]
        _sz   = self._font_size() if hasattr(self, "_font_size") else 13

        # _OFFSET: gap (px) between canvas edge and shell.
        # The two polygon items (fill + border) are drawn in this strip, making
        # the rounded corners genuinely visible.  Canvas window items always
        # render above drawn items regardless of tag_lower/raise, so the only
        # way to expose the border polygons is to keep a gap the shell cannot
        # cover.
        _OFFSET = 2

        cv = tk.Canvas(parent, bg=_wbg, highlightthickness=0, bd=0)
        cv.grid(row=row, column=0, sticky="ew", pady=(0, 10))

        shell = tk.Frame(cv, bg=_cbg)

        # ── Section header ──────────────────────────────────────────
        tk.Label(
            shell, text=title,
            bg=_cbg, fg=_fg,
            font=("TkDefaultFont", _sz, "bold"),
            anchor="w",
        ).pack(fill="x", padx=14, pady=(12, 4))
        tk.Frame(shell, bg=_brd, height=1).pack(fill="x", padx=14, pady=(0, 8))

        # ── Content frame (returned to caller) ─────────────────────
        content = tk.Frame(shell, bg=_cbg)
        content.pack(fill="x", padx=14, pady=(0, 12))
        content.columnconfigure(1, weight=1)   # default: 2-col label+widget

        # ── Canvas ↔ shell resize synchronisation ──────────────────
        # Shell is inset by _OFFSET on every side so the border strip shows.
        win_id = cv.create_window(_OFFSET, _OFFSET, window=shell, anchor="nw")

        def _sync_shell_width(e: tk.Event) -> None:
            cv.itemconfig(win_id, width=max(0, e.width - 2 * _OFFSET))

        def _sync_canvas_height(e: tk.Event) -> None:
            cv.configure(height=shell.winfo_reqheight() + 2 * _OFFSET)
            _draw_border()

        def _draw_border() -> None:
            cv.delete("rd_fill")
            cv.delete("rd_border")
            w = cv.winfo_width()
            h = cv.winfo_height()
            if w > 1 and h > 1:
                # 1. Fill polygon — behind shell (and border)
                draw_rounded_rect(
                    cv, 0, 0, w, h, r=10,
                    fill=_cbg, outline="", tags="rd_fill",
                )
                # 2. Border outline — between fill and shell in z-order
                draw_rounded_rect(
                    cv, 1, 1, w - 1, h - 1, r=10,
                    fill="", outline=_brd, width=1, tags="rd_border",
                )
                # Stack: rd_fill (bottom) → rd_border → shell (top)
                cv.tag_lower("rd_fill")
                cv.tag_lower("rd_border", win_id)

        cv.bind("<Configure>", lambda e: (_sync_shell_width(e), _draw_border()))
        shell.bind("<Configure>", _sync_canvas_height)

        return content

    def _make_rounded_box(
        self,
        parent: tk.Widget,
        fill_color: str,
        border_color: str,
        parent_bg: str,
        *,
        r: int = 8,
        padx: int = 10,
        pady: int = 6,
    ) -> tuple:
        """Rounded-corner coloured info/warning box.

        Returns ``(canvas, shell_frame)`` where *canvas* should be
        grid/packed into the parent and *shell_frame* (``bg=fill_color``)
        is populated by the caller.

        Two-layer rendering:
          • Fill polygon (no outline) placed *below* the shell so the
            fill colour shows through the shell's own transparent corners.
          • Outline-only polygon placed *above* the shell so the rounded
            border is visible on top of the shell's square tkinter corners.
        """
        _OFFSET = 2   # inset gap so border strip is never covered by the shell

        cv = tk.Canvas(parent, bg=parent_bg, highlightthickness=0, bd=0)

        shell = tk.Frame(cv, bg=fill_color, padx=padx, pady=pady)

        win_id = cv.create_window(_OFFSET, _OFFSET, window=shell, anchor="nw")

        def _sync_width(e: tk.Event) -> None:
            cv.itemconfig(win_id, width=max(0, e.width - 2 * _OFFSET))

        def _sync_height(e: tk.Event) -> None:
            cv.configure(height=shell.winfo_reqheight() + 2 * _OFFSET)
            _draw()

        def _draw() -> None:
            cv.delete("rb_fill")
            cv.delete("rb_border")
            w = cv.winfo_width()
            h = cv.winfo_height()
            if w > 1 and h > 1:
                draw_rounded_rect(
                    cv, 0, 0, w, h, r=r,
                    fill=fill_color, outline="", tags="rb_fill",
                )
                draw_rounded_rect(
                    cv, 1, 1, w - 1, h - 1, r=r,
                    fill="", outline=border_color, width=1, tags="rb_border",
                )
                # Stack: rb_fill (bottom) → rb_border → shell (top)
                cv.tag_lower("rb_fill")
                cv.tag_lower("rb_border", win_id)

        cv.bind("<Configure>", lambda e: (_sync_width(e), _draw()))
        shell.bind("<Configure>", _sync_height)

        return cv, shell   # type: ignore[return-value]

    def _make_util_chip(
        self,
        parent: tk.Widget,
        text: str,
        command,
        *,
        parent_bg: str | None = None,
    ) -> "_RoundedChip":
        """Small outlined chip for utility actions (Browse, Reset, Show, etc.)

        Uses ``_RoundedChip`` (canvas-drawn) so macOS native Aqua rendering
        does not override the background or relief.
        """
        c    = self._themed_colors()
        _cbg = c.get("text_bg", "#ffffff")
        _fg  = c["text_fg"]
        _brd = c["input_border"]
        _pbg = c["btn_primary_bg"]
        _sz  = max((self._font_size() if hasattr(self, "_font_size") else 13) - 1, 10)
        pbg  = parent_bg if parent_bg is not None else _cbg
        return _RoundedChip(
            parent, text=text, command=command,
            chip_bg=_cbg, chip_fg=_fg,
            parent_bg=pbg,
            font=("TkDefaultFont", _sz),
            padx=8, pady=3,
            outline=_brd, outline_width=1,
            hover_bg=c.get("qa_bg", "#edf0f8"),
        )

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

        c      = self._themed_colors()
        _wbg   = c["window_bg"]
        _cbg   = c.get("text_bg", "#ffffff")   # white card fill
        _fg    = c["text_fg"]
        _sfg   = c.get("status_fg", "#6b7280")
        _border= c["input_border"]
        _pbg   = c["btn_primary_bg"]
        _pfg   = c["btn_primary_fg"]
        _phov  = c.get("btn_primary_hover", _pbg)

        win = self._make_toplevel()
        win.configure(bg=_wbg)
        win.title(self._t("settings_dialog_title"))
        win.minsize(560, 600)
        win.resizable(True, True)
        self._settings_win = win
        self._settings_wrap_targets = []
        self._settings_wrap_after_id = None

        def _on_settings_configure(_event: tk.Event | None = None) -> None:
            self._schedule_settings_wrap_refresh()

        win.bind("<Configure>", _on_settings_configure, add=True)

        # ── Fixed banner (always visible, above the scroll area) ──────
        _note_sz = max(self._font_size() - 1, 10)  # notice font: 1pt below body, min 10
        banner = tk.Frame(win, background=_wbg, padx=12, pady=8)
        banner.pack(side="top", fill="x")
        tk.Label(
            banner,
            text=self._t("settings_banner"),
            background=_wbg,
            foreground=_sfg,
            font=("TkDefaultFont", _note_sz),
            anchor="w",
        ).pack(side="left")
        # Thin separator line under banner
        tk.Frame(win, bg=_border, height=1).pack(side="top", fill="x")

        # ── Fixed bottom bar (always visible, below the scroll area) ─
        tk.Frame(win, bg=_border, height=1).pack(side="bottom", fill="x")
        bottom_bar = tk.Frame(win, bg=_wbg, padx=10, pady=8)
        bottom_bar.pack(side="bottom", fill="x")

        self._settings_status_var = tk.StringVar(value="")
        _settings_status_lbl = tk.Label(bottom_bar, textvariable=self._settings_status_var,
                                        bg=_wbg, fg=_sfg,
                                        font=("TkDefaultFont", _note_sz),
                                        wraplength=440, anchor="w", justify="left",
                                        )
        _settings_status_lbl.pack(side="left", fill="x", expand=True)
        self._register_settings_wrap_target(_settings_status_lbl, bottom_bar, pad=140)

        _action_frame = tk.Frame(bottom_bar, bg=_wbg)
        _action_frame.pack(side="right")
        _RoundedChip(
            _action_frame, text=self._t("settings_apply_btn"),
            chip_bg=_pbg, chip_fg=_pfg,
            parent_bg=_wbg,
            font=("TkDefaultFont", self._font_size(), "bold"),
            padx=14, pady=6,
            hover_bg=_phov,
            command=self._on_apply_settings,
        ).pack(side="left", padx=(0, 8))
        _RoundedChip(
            _action_frame, text=self._t("settings_close_btn"),
            chip_bg=_wbg, chip_fg=_fg,
            parent_bg=_wbg,
            font=("TkDefaultFont", self._font_size()),
            padx=14, pady=6,
            outline=_border, outline_width=1,
            hover_bg=c.get("qa_bg", "#edf0f8"),
            command=lambda: self._safe_destroy_toplevel(win),
        ).pack(side="left")

        # ── Scrollable canvas inside the dialog ───────────────────────
        canvas = tk.Canvas(win, borderwidth=0, highlightthickness=0, bg=_wbg)
        canvas.pack(side="left", fill="both", expand=True)
        sb = AutoHideScrollbar(
            canvas, orient="vertical",
            color=c.get("sb_color", "#9aa5be"),
            bg=_wbg,
        )
        canvas.configure(yscrollcommand=sb.set)

        inner = tk.Frame(canvas, bg=_wbg, padx=_PAD, pady=_PAD)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(win_id, width=e.width))

        # ── Mouse-wheel scrolling ─────────────────────────────────────
        # Bind at the Toplevel (win) level rather than on every individual
        # widget.  Every child widget's default bindtag list ends with its
        # enclosing Toplevel, so win.bind() fires for scroll events on ANY
        # descendant that does not return "break" from its own bindings.
        # This is simpler and also automatically covers widgets created later
        # (e.g. by _rebuild_emb_context) without any re-binding.
        #
        # Delta handling:
        #   • Physical mouse wheel (Windows) : event.delta is ±120 per notch
        #     → scroll ±1 unit per notch.
        #   • macOS trackpad               : event.delta is continuous and
        #     small (±1…±30 per gesture frame).  Dividing by 120 gives 0,
        #     so instead we use yview_moveto for pixel-accurate smooth scroll.

        def _on_mousewheel(event: tk.Event) -> None:
            try:
                lo, hi = canvas.yview()
                delta = event.delta
                if delta == 0:
                    return
                if abs(delta) >= 120:
                    # Physical scroll wheel: ±1 unit per ±120-delta notch
                    units = int(-delta / 120)
                    if units < 0 and lo <= 0.0:
                        return
                    if units > 0 and hi >= 1.0:
                        return
                    canvas.yview_scroll(units, "units")
                else:
                    # macOS trackpad: fractional pixel-accurate scroll
                    if delta > 0 and lo <= 0.0:
                        return
                    if delta < 0 and hi >= 1.0:
                        return
                    try:
                        sr = canvas.cget("scrollregion")
                        parts = str(sr).split() if sr else []
                        total_h = (float(parts[3]) - float(parts[1])
                                   if len(parts) >= 4 else 0)
                    except Exception:
                        total_h = 0
                    if total_h <= 0:
                        canvas.yview_scroll(-1 if delta > 0 else 1, "units")
                        return
                    canvas.yview_moveto(
                        max(0.0, min(1.0, lo - delta / total_h)))
            except tk.TclError:
                pass  # canvas already destroyed

        def _scroll_up(_e=None):
            canvas.yview_scroll(-1, "units")

        def _scroll_down(_e=None):
            canvas.yview_scroll(1, "units")

        # Toplevel binding: catches all scroll events inside the dialog.
        # Direct bindings on canvas/banner ensure scroll works even when
        # hovering over the viewport area itself.
        for _w in (win, canvas, banner):
            _w.bind("<MouseWheel>", _on_mousewheel, add=True)
            _w.bind("<Button-4>",   _scroll_up,      add=True)   # Linux
            _w.bind("<Button-5>",   _scroll_down,    add=True)   # Linux

        # Destroying the Toplevel automatically removes all its widget-level
        # bindings — no manual cleanup needed.

        inner.columnconfigure(0, weight=1)
        row = 0

        # Helper: small outlined chip button (canvas-drawn → bypasses macOS Aqua)
        def _mk_chip(parent, text, cmd, *, pbg=_cbg):
            return self._make_util_chip(parent, text, cmd, parent_bg=pbg)

        # Helper: effort-style option chip — same art as the Effort chip in
        # the main toolbar.  Displays ``"<current value> ▾"``; clicking opens
        # a tk.Menu positioned directly below the chip.
        #
        # Parameters
        # ----------
        # options_fn : list | callable → list
        #     Static list of option strings, *or* a zero-arg callable that
        #     returns the current list (useful for dynamic lists such as models).
        # on_change  : callable | None
        #     Called with no arguments after a new option is selected.
        # pbg        : str
        #     Parent background (used for the canvas border reveal strip).
        def _mk_option_chip(parent, var, options_fn, *, on_change=None, pbg=_cbg):
            chip_holder: list = [None]

            def _get_opts() -> list:
                return options_fn() if callable(options_fn) else options_fn

            def _show_menu() -> None:
                menu = tk.Menu(win, tearoff=0)
                for opt in _get_opts():
                    def _select(o=opt) -> None:
                        var.set(o)
                        chip_holder[0].set_text(f"{o} ▾")
                        if on_change:
                            on_change()
                    menu.add_command(label=opt, command=_select)
                try:
                    x = chip_holder[0].winfo_rootx()
                    y = (chip_holder[0].winfo_rooty()
                         + chip_holder[0].winfo_height())
                    menu.tk_popup(x, y)
                finally:
                    menu.grab_release()

            _sz  = max(self._font_size() - 1, 10)
            opts = _get_opts()
            # Pre-size the chip to the widest option so it never reflows.
            _size_text = (max([f"{o} ▾" for o in opts], key=len)
                          if opts else f"{var.get()} ▾")
            chip = _RoundedChip(
                parent, text=_size_text,
                chip_bg=c.get("qa_bg", "#edf0f8"), chip_fg=_fg,
                parent_bg=pbg,
                font=("TkDefaultFont", _sz),
                padx=10, pady=4,
                hover_bg=c.get("qa_bg_hover", c.get("qa_bg", "#edf0f8")),
                outline=_border, outline_width=1,
                command=_show_menu,
            )
            chip.set_text(f"{var.get()} ▾")
            chip_holder[0] = chip
            return chip

        # Helper: themed tk.Entry (respects bg/fg on all platforms)
        def _mk_entry(parent, var, *, show="", width=None):
            kw: dict = {}
            if var is not None:
                kw["textvariable"] = var
            if show:
                kw["show"] = show
            if width is not None:
                kw["width"] = width
            return tk.Entry(
                parent,
                bg=_cbg, fg=_fg, insertbackground=_fg,
                relief="flat", bd=0,
                font=("TkDefaultFont", self._font_size()),
                highlightthickness=1,
                highlightbackground=_border,
                highlightcolor=_pbg,
                **kw,
            )

        # ── Model Selection ───────────────────────────────────────────
        mf = self._make_section_card(inner, row, self._t("settings_model_section"), c)
        row += 1

        tk.Label(mf, text=self._t("settings_provider_label"),
                 bg=_cbg, fg=_fg).grid(
            row=0, column=0, sticky="w", padx=(0, 8))
        # Wrap both model-section chips in a compact sub-frame so they share
        # the same width (= the wider chip's natural size) without stretching
        # across the full dialog column.
        _mchips = tk.Frame(mf, bg=_cbg)
        _mchips.grid(row=0, column=1, rowspan=2, sticky="nw")
        _mchips.columnconfigure(0, weight=1)

        _mk_option_chip(
            _mchips, self._llm_provider_var,
            ["gemini", "openai", "deepseek"],
            on_change=self._on_provider_changed,
        ).grid(row=0, column=0, sticky="ew")

        tk.Label(mf, text=self._t("settings_model_label"),
                 bg=_cbg, fg=_fg).grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
        self._model_chip = _mk_option_chip(
            _mchips, self._llm_model_var,
            lambda: models_for(self._llm_provider_var.get()),
            # Re-evaluate upload-button availability when the model changes
            # (some models, e.g. gpt-4o-search-preview, do not accept file inputs
            # even though the provider as a whole supports multimodal uploads).
            on_change=lambda: self._update_tool_btns() if hasattr(self, "_upload_btn") else None,
        )
        self._model_chip.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self._update_model_list()   # populate for current provider

        # ── Per-provider privacy reminder ─────────────────────────────
        _note_sz = max(self._font_size() - 1, 10)
        self._privacy_reminder_var = tk.StringVar()
        _privacy_reminder_lbl = tk.Label(
            mf, textvariable=self._privacy_reminder_var,
            bg=_cbg, fg=c.get("status_fg", "#6b7280"),
            font=("TkDefaultFont", _note_sz),
            wraplength=400, anchor="w", justify="left",
        )
        _privacy_reminder_lbl.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self._register_settings_wrap_target(_privacy_reminder_lbl, mf, pad=36)

        self._privacy_policy_lbl = tk.Label(
            mf, text="",
            bg=_cbg, fg=c.get("link_fg", "#1b3167"),
            font=("TkDefaultFont", _note_sz, "underline"),
            cursor="hand2", anchor="w",
        )
        self._privacy_policy_lbl.grid(row=3, column=0, columnspan=2, sticky="w",
                                      pady=(2, 0))
        self._update_privacy_reminder()   # populate immediately for current provider

        # ── Request Frequency ─────────────────────────────────────────
        rf = self._make_section_card(inner, row, self._t("settings_rate_section"), c)
        row += 1

        tk.Label(rf, text=self._t("settings_rate_tier_label"),
                 bg=_cbg, fg=_fg).grid(
            row=0, column=0, sticky="w", padx=(0, 8))

        from uacragent.domain.rate_tiers import (
            RATE_TIER_BY_DISPLAY, display_names, get_rate_tier)

        # Dynamic hint label — defined before the chip so the on_change
        # callback can safely reference it.
        self._rate_hint_var = tk.StringVar()
        _rate_hint_lbl = tk.Label(
            rf, textvariable=self._rate_hint_var,
            bg=_cbg, fg="#6b7280",
            font=("TkDefaultFont", max(self._font_size() - 1, 10)),
            wraplength=460, anchor="w", justify="left",
        )
        _rate_hint_lbl.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self._register_settings_wrap_target(_rate_hint_lbl, rf, pad=36)

        def _update_rate_hint(*_: object) -> None:
            disp = self._rate_tier_disp_var.get()
            tier_id = RATE_TIER_BY_DISPLAY.get(disp, "free")
            tier    = get_rate_tier(tier_id)
            self._rate_hint_var.set(self._t(tier.hint_i18n_key))
            # Refresh the suggestion label whenever the tier selection changes.
            self._update_rate_suggestion()

        _mk_option_chip(
            rf, self._rate_tier_disp_var, display_names,
            on_change=_update_rate_hint,
        ).grid(row=0, column=1, sticky="w")
        _update_rate_hint()   # populate immediately for the current selection

        # Suggestion label — blue info tone; only visible when current ≠ suggested.
        self._rate_suggestion_var = tk.StringVar()
        _rate_suggestion_lbl = tk.Label(
            rf, textvariable=self._rate_suggestion_var,
            bg=_cbg, fg="#1565c0",
            font=("TkDefaultFont", max(self._font_size() - 1, 10)),
            wraplength=460, anchor="w", justify="left",
        )
        _rate_suggestion_lbl.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(2, 0))
        self._register_settings_wrap_target(_rate_suggestion_lbl, rf, pad=36)

        # ── API Key (single row, changes with provider) ───────────────
        akf = self._make_section_card(inner, row, self._t("settings_api_key_section"), c)
        akf.columnconfigure(2, weight=0)
        akf.columnconfigure(3, weight=0)
        row += 1

        self._api_key_label_var = tk.StringVar(value=self._t("api_key_google"))
        tk.Label(akf, textvariable=self._api_key_label_var,
                 bg=_cbg, fg=_fg).grid(
            row=0, column=0, sticky="w", padx=(0, 8))

        # Single entry — textvariable is swapped by _update_api_key_row()
        self._active_key_entry = _mk_entry(akf, None, show="*")
        self._active_key_entry.grid(row=0, column=1, sticky="ew", padx=(0, 4))

        self._api_key_show_btn = _mk_chip(
            akf, self._t("settings_show_key"),
            lambda: self._toggle_key_entry(
                self._active_key_entry, self._api_key_show_btn))
        self._api_key_show_btn.grid(row=0, column=2)

        self._api_key_hint_var = tk.StringVar()
        self._api_key_hint_lbl = tk.Label(
            akf, textvariable=self._api_key_hint_var,
            bg=_cbg, fg="gray",
            font=("TkDefaultFont", _note_sz))
        self._api_key_hint_lbl.grid(row=0, column=3, padx=(6, 0))

        # Wire entry to current provider's var and update hint
        self._update_api_key_row()

        # ── API key scope notice (rounded info box) ──────────────────────────
        _info_bg  = c.get("info_bg",     "#e8f4fd")
        _info_brd = c.get("info_border", "#90caf9")
        _info_fg  = c.get("info_fg",     "#0d47a1")
        _note_cv, _note_shell = self._make_rounded_box(
            akf, fill_color=_info_bg, border_color=_info_brd,
            parent_bg=_cbg, r=8, padx=10, pady=6)
        _note_cv.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        _api_key_note_lbl = tk.Label(
            _note_shell,
            text=self._t("settings_api_key_note"),
            background=_info_bg, foreground=_info_fg,
            font=("TkDefaultFont", _note_sz), anchor="w", justify="left", wraplength=440,
        )
        _api_key_note_lbl.pack(fill="x")
        self._register_settings_wrap_target(_api_key_note_lbl, akf, pad=48)

        # ── Embedding ─────────────────────────────────────────────────────
        embf = self._make_section_card(inner, row, self._t("settings_embedding_section"), c)
        row += 1

        tk.Label(embf, text=self._t("settings_provider_label"),
                 bg=_cbg, fg=_fg).grid(
            row=0, column=0, sticky="w", padx=(0, 8))
        _mk_option_chip(
            embf, self._emb_provider_disp_var,
            list(self._EMB_PROVIDER_OPTIONS.keys()),
            on_change=self._on_emb_provider_changed,
        ).grid(row=0, column=1, sticky="w")

        # Context row — swapped by _on_emb_provider_changed()
        self._emb_context_frame = tk.Frame(embf, bg=_cbg)
        self._emb_context_frame.grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self._emb_context_frame.columnconfigure(1, weight=1)
        self._rebuild_emb_context()   # populate for current provider

        # ── Course Information ─────────────────────────────────────────
        inf = self._make_section_card(inner, row, self._t("settings_course_section"), c)
        row += 1

        fields = [
            (self._t("settings_course_name_field"), "red", self._course_name_var),
            (self._t("settings_university_field"),  None,  self._university_var),
            (self._t("settings_major_field"),        None,  self._major_var),
            (self._t("settings_course_code_field"), None,  self._course_code_var),
            (self._t("settings_professor_field"),   None,  self._professor_var),
            (self._t("settings_semester_field"),    None,  self._semester_var),
        ]
        for fi, (_lbl_text, _lbl_color, var) in enumerate(fields):
            _lbl_fg = _lbl_color if _lbl_color else _fg
            tk.Label(inf, text=_lbl_text + ":", bg=_cbg, fg=_lbl_fg).grid(
                row=fi, column=0, sticky="w", padx=(0, 6), pady=(3, 0))
            e = _mk_entry(inf, var)
            e.grid(row=fi, column=1, sticky="ew", pady=(3, 0), ipady=3)
            if _lbl_text == self._t("settings_course_name_field"):
                self._course_name_entry = e

        # ── Exam Options ──────────────────────────────────────────────
        ef = self._make_section_card(inner, row, self._t("settings_exam_section"), c)
        row += 1

        tk.Label(ef, text=self._t("settings_exam_type_label"),
                 bg=_cbg, fg=_fg).grid(
            row=0, column=0, sticky="w", padx=(0, 6))
        tk.Label(ef, text=self._t("settings_exam_format_label"),
                 bg=_cbg, fg=_fg).grid(
            row=1, column=0, sticky="w", padx=(0, 6), pady=(4, 0))

        # Wrap both exam chips in a compact sub-frame so they share the same
        # width (= the wider chip's natural size) without filling the column.
        _echips = tk.Frame(ef, bg=_cbg)
        _echips.grid(row=0, column=1, rowspan=2, sticky="nw")
        _echips.columnconfigure(0, weight=1)

        _mk_option_chip(
            _echips, self._exam_type_var,
            [e.value for e in ExamType],
        ).grid(row=0, column=0, sticky="ew")

        _mk_option_chip(
            _echips, self._exam_format_var,
            [e.value for e in ExamFormat],
        ).grid(row=1, column=0, sticky="ew", pady=(4, 0))

        tk.Label(ef, text=self._t("settings_exam_duration_label"),
                 bg=_cbg, fg=_fg).grid(
            row=2, column=0, sticky="w", padx=(0, 6), pady=(4, 0))
        _mk_entry(ef, self._exam_duration_var).grid(
            row=2, column=1, sticky="ew", pady=(4, 0), ipady=3)

        tk.Label(ef, text=self._t("settings_exam_info_label"),
                 bg=_cbg, fg=_fg).grid(
            row=3, column=0, sticky="w", padx=(0, 6), pady=(4, 0))
        ei_row = tk.Frame(ef, bg=_cbg)
        ei_row.grid(row=3, column=1, sticky="ew", pady=(4, 0))
        ei_row.columnconfigure(0, weight=1)
        self._exam_info_path_label = tk.Label(
            ei_row, textvariable=self._exam_info_path_var,
            bg=_cbg, fg="gray", anchor="w")
        self._exam_info_path_label.grid(row=0, column=0, sticky="ew")
        _mk_chip(ei_row, self._t("settings_browse_btn"),
                 self._on_pick_exam_info).grid(row=0, column=1, padx=(4, 0))
        _mk_chip(ei_row, self._t("settings_clear_btn"),
                 self._on_clear_exam_info).grid(row=0, column=2, padx=(4, 0))

        # ── Workspace & Export ────────────────────────────────────────
        wf = self._make_section_card(inner, row, self._t("settings_workspace_section"), c)
        row += 1

        tk.Label(wf, text=self._t("settings_workspace_label"),
                 bg=_cbg, fg=_fg).grid(
            row=0, column=0, sticky="w", padx=(0, 6))
        ws_row = tk.Frame(wf, bg=_cbg)
        ws_row.grid(row=0, column=1, sticky="ew")
        ws_row.columnconfigure(0, weight=1)
        if self._workspace_committed:
            # Locked: show the path as a read-only label + Open button
            path_text = self._workspace_var.get() or str(get_app_data_dir())
            tk.Label(ws_row, text=path_text, bg=_cbg, fg="#1a56a5",
                     anchor="w").grid(row=0, column=0, sticky="ew")
            _mk_chip(ws_row, self._t("settings_open_btn"),
                     lambda: _open_folder_in_os(path_text)
                     ).grid(row=0, column=1, padx=(4, 0))
            tk.Label(ws_row, text="🔒", bg=_cbg, fg="gray"
                     ).grid(row=0, column=2, padx=(4, 0))
        else:
            # Not yet committed: allow an optional custom workspace selection.
            self._workspace_label = tk.Label(
                ws_row,
                bg=_cbg, fg="gray", anchor="w", justify="left", wraplength=360,
            )
            self._workspace_label.grid(row=0, column=0, sticky="ew")
            self._register_settings_wrap_target(self._workspace_label, ws_row, pad=120)
            self._workspace_pick_btn = _mk_chip(
                ws_row,
                self._t("settings_set_btn"),
                self._on_pick_workspace,
            )
            self._workspace_pick_btn.grid(row=0, column=1, padx=(4, 0))
            self._workspace_clear_btn = _mk_chip(
                ws_row,
                self._t("settings_clear_btn"),
                self._on_reset_workspace,
            )
            self._workspace_clear_btn.grid(row=0, column=2, padx=(4, 0))
            self._refresh_workspace_label()

        # ── Deletion warning (rounded warning box) ────────────────────────
        _warn_bg       = c.get("warn_bg",       "#fff3e0")
        _warn_brd      = c.get("warn_border",    "#e65100")
        _warn_title_fg = c.get("warn_title_fg",  "#bf360c")
        _warn_body_fg  = c.get("warn_body_fg",   "#4e342e")
        _warn_cv, _warn_shell = self._make_rounded_box(
            wf, fill_color=_warn_bg, border_color=_warn_brd,
            parent_bg=_cbg, r=8, padx=10, pady=6)
        _warn_cv.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 2))
        tk.Label(
            _warn_shell,
            text=self._t("settings_deletion_warning_title"),
            background=_warn_bg, foreground=_warn_title_fg,
            font=("TkDefaultFont", _note_sz, "bold"),
            anchor="w",
        ).pack(side="top", fill="x")
        _warn_body_lbl = tk.Label(
            _warn_shell,
            text=self._t("settings_deletion_warning_body"),
            background=_warn_bg, foreground=_warn_body_fg,
            font=("TkDefaultFont", _note_sz),
            anchor="w", justify="left", wraplength=440,
        )
        _warn_body_lbl.pack(side="top", fill="x")
        self._register_settings_wrap_target(_warn_body_lbl, wf, pad=48)

        tk.Label(wf, text=self._t("settings_export_format_label"),
                 bg=_cbg, fg=_fg).grid(
            row=2, column=0, sticky="w", padx=(0, 6), pady=(6, 0))
        _mk_option_chip(
            wf, self._export_format_var,
            [e.value for e in ExportFormat],
        ).grid(row=2, column=1, sticky="w", pady=(6, 0))

        tk.Label(wf, text=self._t("settings_extra_instructions_label"),
                 bg=_cbg, fg=_fg).grid(
            row=3, column=0, sticky="nw", padx=(0, 6), pady=(6, 0))
        self._extra_text = tk.Text(
            wf, height=3, wrap="word",
            bg=_cbg, fg=_fg, insertbackground=_fg,
            relief="flat", bd=0,
            font=("TkDefaultFont", self._font_size()),
            highlightthickness=1,
            highlightbackground=_border,
            highlightcolor=_pbg,
        )
        self._extra_text.grid(row=3, column=1, sticky="ew", pady=(6, 0))
        self._extra_text.insert("1.0", self._extra_instructions_var.get())

        # ── Course Documents ──────────────────────────────────────────
        docs_frame = self._make_section_card(inner, row, self._t("settings_docs_section"), c)
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
        out_frame = self._make_section_card(inner, row, self._t("settings_outputs_section"), c)
        out_frame.columnconfigure(0, weight=1)
        row += 1
        self._build_outputs_panel(out_frame, win)

        # Wire the OS-level window-close button (×) to the same safe destroy
        # used by the in-dialog Close button.  Without this, clicking × calls
        # Tkinter's raw destroy() directly, which races with widget command
        # teardown and raises TclError: can't delete Tcl command.
        win.protocol(
            "WM_DELETE_WINDOW",
            lambda: self._safe_destroy_toplevel(win),
        )
        self._center_on_main(win)

    def _build_outputs_panel(
        self, parent: tk.Frame, dialog_win: tk.Toplevel
    ) -> None:
        """Populate the Generated Outputs section inside the Settings dialog.

        Lists every file in ``<workspace>/.uacragent/outputs/`` and provides
        per-file Open, Copy, and Delete buttons plus an "Open folder" shortcut.
        The panel re-renders itself after a deletion so the list stays current.
        """
        # Resolve the outputs folder for the current session.
        ws_id     = self._session.workspace_id
        ws_folder = self._session.workspace_folder
        c    = self._themed_colors()
        _cbg = c.get("text_bg", "#ffffff")
        _fg  = c.get("status_fg", "#6b7280")

        if not ws_id and not ws_folder:
            tk.Label(parent, text=self._t("settings_no_workspace"),
                     bg=_cbg, fg=_fg).pack(anchor="w")
            return

        ws = workspace_paths(workspace_id=ws_id, workspace_folder=ws_folder)
        out_dir = Path(ws.outputs)

        # Container that we re-fill on every refresh
        list_frame = tk.Frame(parent, bg=_cbg)
        list_frame.pack(fill="x")
        list_frame.columnconfigure(0, weight=1)

        # "Open folder" shortcut below the list — disabled until the folder exists
        footer = tk.Frame(parent, bg=_cbg)
        footer.pack(fill="x", pady=(6, 0))
        open_folder_btn = self._make_util_chip(
            footer, self._t("settings_open_outputs_btn"),
            lambda: _open_folder_in_os(str(out_dir)),
            parent_bg=_cbg,
        )
        open_folder_btn.pack(side="left")

        def _refresh() -> None:
            # Wipe and rebuild the file rows
            for w in list_frame.winfo_children():
                w.destroy()

            files: list[Path] = []
            if out_dir.exists():
                # Guard each stat() call against TOCTOU: a file may be deleted
                # between iterdir() materialising its path and stat() reading it.
                def _safe_mtime(p: Path) -> float:
                    try:
                        return p.stat().st_mtime
                    except OSError:
                        return 0.0

                files = sorted(out_dir.iterdir(), key=_safe_mtime, reverse=True)
                # Exclude hidden/system files (e.g. .DS_Store on macOS,
                # Thumbs.db on Windows) — only real user-visible outputs.
                files = [
                    f for f in files
                    if f.is_file() and not f.name.startswith(".")
                    and f.name not in {"Thumbs.db", "desktop.ini"}
                ]

            # Enable/disable the "Open folder" button based on folder existence
            open_folder_btn.set_state(out_dir.exists())

            if not files:
                msg = (self._t("settings_no_outputs")
                       if out_dir.exists()
                       else self._t("settings_no_outputs_folder"))
                tk.Label(list_frame, text=msg,
                         bg=_cbg, fg=_fg).grid(row=0, column=0, sticky="w",
                                                pady=(2, 0))
                return

            _row_even = c.get("row_even_bg", "#f7f7f7")
            _row_odd  = c.get("row_odd_bg",  "#ffffff")
            for row_idx, fpath in enumerate(files):
                bg = _row_even if row_idx % 2 == 0 else _row_odd

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
                    background=bg, fg=c.get("text_fg", "#1a2744"),
                    anchor="w",
                )
                name_lbl.grid(row=0, column=0, sticky="ew", padx=(4, 8))

                btn_cell = tk.Frame(row_f, bg=bg)
                btn_cell.grid(row=0, column=1, padx=(0, 4), pady=2)

                # Open
                self._make_util_chip(
                    btn_cell, self._t("output_open_btn"),
                    lambda p=str(fpath): _open_file_in_os(
                        p,
                        on_error=lambda msg: self._append_chat("system", f"⚠️ {msg}"),
                    ),
                    parent_bg=bg,
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
                    # Avoid overwriting: append _1, _2 … if the file exists.
                    # Cap at 1 000 to match the rest of the codebase and
                    # prevent hanging the GUI thread on a pathological
                    # destination directory.
                    stem, suffix = src.stem, src.suffix
                    counter = 1
                    while dest.exists():
                        if counter > 1_000:
                            self._show_info_dialog(
                                self._t("mb_copy_fail_title"),
                                self._t("mb_copy_fail_too_many"),
                            )
                            return
                        dest = Path(dest_dir) / f"{stem}_{counter}{suffix}"
                        counter += 1
                    try:
                        if src.is_symlink():
                            raise OSError(
                                f"'{src.name}' is a symlink and cannot be copied."
                            )
                        _shutil.copy2(str(src), str(dest))
                        self._show_info_dialog(
                            self._t("mb_copy_title"),
                            self._t("mb_copy_body").format(dest=dest))
                    except Exception as exc:
                        self._show_info_dialog(
                            self._t("mb_copy_fail_title"), str(exc))

                self._make_util_chip(
                    btn_cell, self._t("output_copy_btn"), _copy_to,
                    parent_bg=bg,
                ).pack(side="left", padx=(0, 3))

                # Delete
                def _delete(p: Path = fpath) -> None:
                    if not self._show_confirm_dialog(
                        self._t("mb_delete_file_title"),
                        self._t("mb_delete_file_body").format(name=p.name),
                        confirm_text=self._t("output_delete_btn"),
                        destructive=True,
                    ):
                        return
                    try:
                        if p.is_symlink():
                            raise OSError(
                                f"'{p.name}' is a symlink and cannot be deleted here."
                            )
                        p.unlink()
                    except Exception as exc:
                        self._show_info_dialog(
                            self._t("mb_delete_fail_title"), str(exc))
                        return
                    _refresh()

                self._make_util_chip(
                    btn_cell, self._t("output_delete_btn"), _delete,
                    parent_bg=bg,
                ).pack(side="left")

        _refresh()

    def _create_doc_section(self, parent: tk.Frame,
                            doc_type: DocumentType) -> None:
        c     = self._themed_colors()
        _cbg  = c.get("text_bg", "#ffffff")   # white card background
        _fg   = c["text_fg"]
        _brd  = c["input_border"]
        _sz   = self._font_size() if hasattr(self, "_font_size") else 13
        label = self._t(f"doctype_{doc_type.value}")

        _OFFSET = 2
        # Canvas-based rounded box — same two-layer pattern as _make_section_card.
        cv = tk.Canvas(parent, bg=_cbg, highlightthickness=0, bd=0)
        cv.pack(fill="x", pady=3)

        shell = tk.Frame(cv, bg=_cbg)
        win_id = cv.create_window(_OFFSET, _OFFSET, window=shell, anchor="nw")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=0)
        shell.rowconfigure(1, weight=1, minsize=55)
        shell.rowconfigure(2, weight=0, minsize=28)

        def _sync_shell_width(e: tk.Event) -> None:
            cv.itemconfig(win_id, width=max(0, e.width - 2 * _OFFSET))

        def _sync_canvas_height(e: tk.Event) -> None:
            cv.configure(height=shell.winfo_reqheight() + 2 * _OFFSET)
            _draw()

        def _draw() -> None:
            cv.delete("ds_fill")
            cv.delete("ds_border")
            w, h = cv.winfo_width(), cv.winfo_height()
            if w > 1 and h > 1:
                draw_rounded_rect(cv, 0, 0, w, h, r=8,
                                  fill=_cbg, outline="", tags="ds_fill")
                draw_rounded_rect(cv, 1, 1, w - 1, h - 1, r=8,
                                  fill="", outline=_brd, width=1, tags="ds_border")
                cv.tag_lower("ds_fill")
                cv.tag_lower("ds_border", win_id)

        cv.bind("<Configure>", lambda e: (_sync_shell_width(e), _draw()))
        shell.bind("<Configure>", _sync_canvas_height)

        tk.Label(
            shell, text=label,
            bg=_cbg, fg=_fg,
            font=("TkDefaultFont", _sz),
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=6, pady=(6, 2))

        # Wrapper frame holds the listbox + overlay scrollbar (spans both cols)
        lb_wrap = tk.Frame(shell, bg=_cbg)
        lb_wrap.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=6)
        lb = tk.Listbox(
            lb_wrap, height=3, selectmode=tk.EXTENDED,
            bg=c.get("text_bg", "#ffffff"),
            fg=c.get("text_fg", "#1a2744"),
            selectbackground=c.get("lb_sel_bg", "#1b3167"),
            selectforeground=c.get("lb_sel_fg", "#ffffff"),
            borderwidth=0, highlightthickness=0,
            relief="flat",
        )
        lb.pack(fill="both", expand=True)
        lb_vsb = AutoHideScrollbar(
            lb_wrap, orient="vertical",
            color=c.get("sb_color", "#9aa5be"),
            bg=c.get("text_bg", "#ffffff"),
        )
        lb.configure(yscrollcommand=lb_vsb.set)
        self._file_listboxes[doc_type] = lb

        btn_row = tk.Frame(shell, bg=_cbg)
        btn_row.grid(row=2, column=0, columnspan=2, sticky="w", padx=6, pady=(3, 6))
        self._make_util_chip(
            btn_row, self._t("settings_add_files_btn"),
            lambda dt=doc_type: self._on_add_files(dt),
            parent_bg=_cbg,
        ).pack(side="left", padx=(0, 6))
        self._make_util_chip(
            btn_row, self._t("settings_remove_files_btn"),
            lambda dt=doc_type: self._on_remove_files(dt),
            parent_bg=_cbg,
        ).pack(side="left")

    def _settings_alive(self) -> bool:
        """Return True only when the Settings Toplevel exists and is not destroyed."""
        return (
            self._settings_win is not None
            and self._settings_win.winfo_exists()
        )

    def _update_model_list(self) -> None:
        """Refresh the model chip for the current provider.

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
        # Update the chip's displayed text when the dialog is alive.
        # The chip's _show_menu() closure calls models_for() dynamically,
        # so the drop-down list is always up-to-date without further action.
        if self._settings_alive() and hasattr(self, "_model_chip"):
            try:
                self._model_chip.set_text(f"{self._llm_model_var.get()} ▾")
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
            self._api_key_show_btn.configure(text=self._t("settings_show_key"))
            self._api_key_hint_lbl.configure(
                fg="gray" if env_key else "#cc4400")
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

        c    = self._themed_colors()
        _cbg = c.get("text_bg", "#ffffff")
        _fg  = c["text_fg"]

        provider = self._emb_provider_var.get()

        _brd = c["input_border"]
        _pbg = c["btn_primary_bg"]
        _sz  = self._font_size() if hasattr(self, "_font_size") else 13

        if provider == "local":
            # Free model selector
            tk.Label(frame, text=self._t("settings_model_label"),
                     bg=_cbg, fg=_fg).grid(
                row=0, column=0, sticky="w", padx=(0, 8))

            # ── Install-status helpers ─────────────────────────────────────
            def _badge(display_name: str) -> str:
                """Return '✓' when model is cached locally, '⬇' otherwise."""
                model_id = self._available_local_embedding_models().get(display_name, "")
                if not model_id:
                    return "  ⬇"   # unknown display name → not cached
                return "  ✓" if self._is_model_cached(model_id) else "  ⬇"

            def _chip_text(display_name: str) -> str:
                return f"{display_name}{_badge(display_name)} ▾"

            def _on_local_model_selected() -> None:
                disp = self._local_model_disp_var.get()
                self._local_model_var.set(
                    self._available_local_embedding_models().get(
                        disp, "all-MiniLM-L6-v2"
                    )
                )
                # Refresh chip label so the badge reflects actual cache state.
                if _local_chip_holder[0] is not None:
                    _local_chip_holder[0].set_text(_chip_text(disp))

            # Build a chip sized to the widest possible label (badge included).
            _chip_sz = max(_sz - 1, 10)
            _local_opts = list(self._available_local_embedding_models().keys())
            # Use the longest badge (✓ and ⬇ occupy the same width; ✓ is fine)
            _local_size_text = max(
                [f"{o}  ✓ ▾" for o in _local_opts], key=len) if _local_opts else ""
            _local_chip_holder: list = [None]

            def _show_local_menu() -> None:
                menu = tk.Menu(frame, tearoff=0)
                for opt in _local_opts:
                    # Recompute badge at menu-open time so it reflects the
                    # current cache state even if something was just installed.
                    menu_label = f"{opt}{_badge(opt)}"
                    def _sel(o=opt) -> None:
                        self._local_model_disp_var.set(o)
                        _local_chip_holder[0].set_text(_chip_text(o))
                        _on_local_model_selected()
                    menu.add_command(label=menu_label, command=_sel)
                try:
                    x = _local_chip_holder[0].winfo_rootx()
                    y = (_local_chip_holder[0].winfo_rooty()
                         + _local_chip_holder[0].winfo_height())
                    menu.tk_popup(x, y)
                finally:
                    menu.grab_release()

            c_chip = self._themed_colors()
            _local_chip = _RoundedChip(
                frame, text=_local_size_text,
                chip_bg=c_chip.get("qa_bg", "#edf0f8"),
                chip_fg=c_chip["text_fg"],
                parent_bg=_cbg,
                font=("TkDefaultFont", _chip_sz),
                padx=10, pady=4,
                hover_bg=c_chip.get("qa_bg_hover",
                                    c_chip.get("qa_bg", "#edf0f8")),
                outline=c_chip["input_border"], outline_width=1,
                command=_show_local_menu,
            )
            _local_chip.set_text(_chip_text(self._local_model_disp_var.get()))
            _local_chip_holder[0] = _local_chip
            _local_chip.grid(row=0, column=1, sticky="w")

            # ── Legend ────────────────────────────────────────────────────
            tk.Label(
                frame,
                text=self._t("settings_emb_cache_legend"),
                bg=_cbg, fg="#6b7280",
                font=("TkDefaultFont", max(_sz - 2, 9)),
                anchor="w",
            ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))

            _local_hint_lbl = tk.Label(
                frame,
                text=self._t("settings_emb_local_hint"),
                bg=_cbg, fg="#6b7280",
                font=("TkDefaultFont", max(_sz - 1, 10)),
                wraplength=400, anchor="w", justify="left",
            )
            _local_hint_lbl.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(2, 0))
            self._register_settings_wrap_target(_local_hint_lbl, frame, pad=24)
        else:
            # API-based: show a key entry field for the embedding provider.
            env_var = "GOOGLE_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
            key_var = self._gemini_key_var if provider == "gemini" else self._openai_key_var
            label   = self._t("api_key_google") if provider == "gemini" else self._t("api_key_openai")

            frame.columnconfigure(1, weight=1)
            tk.Label(frame, text=label, bg=_cbg, fg=_fg).grid(
                row=0, column=0, sticky="w", padx=(0, 8))

            emb_entry = tk.Entry(
                frame, textvariable=key_var, show="*",
                bg=_cbg, fg=_fg, insertbackground=_fg,
                relief="flat", bd=0,
                font=("TkDefaultFont", _sz),
                highlightthickness=1,
                highlightbackground=_brd,
                highlightcolor=_pbg,
            )
            emb_entry.grid(row=0, column=1, sticky="ew", padx=(0, 4), ipady=3)

            show_btn_ref: list = []
            show_btn_ref.append(self._make_util_chip(
                frame, self._t("settings_show_key"),
                lambda: self._toggle_key_entry(emb_entry, show_btn_ref[0]),
                parent_bg=_cbg,
            ))
            show_btn_ref[0].grid(row=0, column=2)

            # Status hint below the entry
            key_present = bool(os.environ.get(env_var, "").strip())
            if key_present:
                hint     = self._t("emb_hint_loaded").format(env_var=env_var)
                hint_fg  = "#6b7280"
            else:
                hint     = self._t("emb_hint_missing").format(env_var=env_var)
                hint_fg  = "#cc4400"
            _emb_hint_lbl = tk.Label(frame, text=hint, bg=_cbg, fg=hint_fg,
                                     font=("TkDefaultFont", max(_sz - 1, 10)),
                                     wraplength=400, anchor="w", justify="left",
                                     )
            _emb_hint_lbl.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(3, 0))
            self._register_settings_wrap_target(_emb_hint_lbl, frame, pad=24)

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
        """Return True if the embedding model is already fully downloaded.

        Delegates to the same helpers used by the actual download code so the
        check is always consistent with what the runtime will find on disk.

        * **Frozen .app** — checks the app-managed Chroma ONNX cache
          (``<app_data_dir>/models/chroma/onnx_models/…/onnx/model.onnx``).
        * **Source mode** — checks the app-managed HuggingFace Hub cache
          (``<app_data_dir>/models/models--…/snapshots/…/pytorch_model.bin``).

        This reflects the current runtime split: source installs use the
        app-managed HuggingFace cache, while frozen builds use the packaged
        ONNX local backend under the same app-managed data tree.

        The old implementation used ``huggingface_hub.scan_cache_dir()``, which
        scans the system-wide HF cache directory and ignores the app's custom
        ``HF_HUB_CACHE`` path.  It also had no awareness of the ONNX path used
        in frozen builds, so the download dialog reappeared on every Apply even
        after a successful first download in the frozen .app.
        """
        import sys as _sys
        from uacragent.infra.vectorstore import (
            _hf_model_is_cached,
            _onnx_model_is_cached,
        )
        if getattr(_sys, "frozen", False) and model_name == "all-MiniLM-L6-v2":
            return _onnx_model_is_cached()
        return _hf_model_is_cached(model_name)

    def _confirm_model_download(self) -> bool:
        """Show a confirmation dialog before downloading a local embedding model.

        Returns True if the user confirmed (or the model is already cached),
        False if the user cancelled.

        Two situations trigger a download prompt:

        1. **Explicit local provider** — the user-selected model is not yet
           cached on disk.
        2. **Cloud provider with missing API key** — the runtime will fall back
           to the default local model (all-MiniLM-L6-v2) automatically; the
           prompt warns the user *before* the background thread starts so they
           can decide whether to proceed.

        Reads from ``os.environ`` (the committed state) rather than the live
        UI StringVars so that sidebar-triggered indexing (where the Settings
        dialog is closed) always sees the correct provider and model.
        """
        from uacragent.infra.vectorstore import _DEFAULT_LOCAL_MODEL

        # ── Determine which model will actually be used ───────────────────
        # Use os.environ (committed by _inject_api_keys on Apply) as the
        # ground truth; fall back to the live UI vars only when env is absent.
        provider = os.environ.get("EMBEDDING_PROVIDER",
                                  self._emb_provider_var.get() or "gemini")

        if provider == "local":
            # Explicit local provider: check the user-selected model.
            model_name = self._normalize_local_embedding_model(os.environ.get(
                "LOCAL_EMBEDDING_MODEL",
                self._local_model_var.get() or _DEFAULT_LOCAL_MODEL,
            ))
        elif not self._has_embedding_key():
            # Cloud key is absent — runtime will silently fall back to the
            # default local model.  Pre-check so the user can decide now.
            model_name = self._normalize_local_embedding_model(_DEFAULT_LOCAL_MODEL)
        else:
            # Cloud provider with a key: no local download will occur.
            return True

        if self._is_model_cached(model_name):
            return True  # already on disk — nothing to download

        # ── Model not cached — ask the user ───────────────────────────────
        # Look up the display label to extract the size hint (e.g. "~80 MB").
        disp = self._local_model_display_label(model_name)
        size_match = re.search(r"~([\d.]+ MB)", disp)
        size_str = size_match.group(1) if size_match else "unknown size"

        from uacragent.infra.persistence import (
            get_chroma_onnx_model_dir,
            get_hf_cache_dir,
        )
        cache_dir = (
            get_chroma_onnx_model_dir(model_name)
            if getattr(sys, "frozen", False) and model_name == _DEFAULT_LOCAL_MODEL
            else get_hf_cache_dir()
        )

        return self._show_confirm_dialog(
            self._t("mb_dl_model_title"),
            self._t("mb_dl_model_body").format(
                model_name=model_name,
                size_str=size_str,
                cache_dir=cache_dir,
            ),
            confirm_text=self._t("btn_download"),
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

    def _update_privacy_reminder(self) -> None:
        """Refresh the per-provider privacy reminder inside Session Settings.

        Updates both the reminder text label (via StringVar) and the clickable
        privacy-policy link whenever the selected provider changes.  Safe to
        call when the dialog is closed — exits immediately via the ``hasattr``
        guard.
        """
        if not hasattr(self, "_privacy_reminder_var"):
            return  # dialog not yet built — nothing to update

        from uacragent.domain.providers import get_provider
        provider_id  = self._llm_provider_var.get() or "gemini"
        provider_cfg = get_provider(provider_id)
        reminder     = self._t("privacy_reminder").format(
            provider=provider_cfg.display_name)
        try:
            self._privacy_reminder_var.set(reminder)
        except Exception:  # noqa: BLE001
            return

        if not hasattr(self, "_privacy_policy_lbl"):
            return
        try:
            policy_url = provider_cfg.privacy_policy_url
            if policy_url:
                btn_text = self._t("privacy_policy_btn").format(
                    provider=provider_cfg.display_name)
                self._privacy_policy_lbl.configure(text=btn_text)
                self._privacy_policy_lbl.bind(
                    "<Button-1>",
                    lambda _e, url=policy_url: _open_in_os(url),
                )
            else:
                self._privacy_policy_lbl.configure(text="")
                self._privacy_policy_lbl.unbind("<Button-1>")
        except tk.TclError:
            pass  # widget already destroyed — harmless

    def _on_provider_changed(self, _event: object = None) -> None:
        """React to the user selecting a different LLM provider in the dropdown.

        Refreshes the model list, API-key row label, rate-tier suggestion, and
        the privacy reminder to match the newly selected provider.
        """
        self._update_model_list()
        self._update_api_key_row()
        self._update_rate_suggestion()
        self._update_privacy_reminder()

    def _toggle_key_entry(self, entry: tk.Widget, btn: tk.Widget | None = None) -> None:
        """Toggle the API-key entry field between masked (``***``) and plaintext.

        Flips the ``show`` option on *entry* and updates *btn*'s label to match
        the new state so the user knows which action another click will perform.
        """
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
            title=self._t("pick_exam_info_title"),
            filetypes=[("All supported", "*.pdf *.txt *.md *.docx *.pptx *.ppt"),
                       ("PDF", "*.pdf"), ("Text", "*.txt"),
                       ("Markdown", "*.md"), ("Word", "*.docx"),
                       ("Presentations", "*.pptx *.ppt")])
        if path:
            self._exam_info_path_var.set(path)
            if hasattr(self, "_exam_info_path_label"):
                self._exam_info_path_label.configure(foreground="black")
            # Warn immediately if the file is larger than the LLM-injection cap.
            try:
                from uacragent.agent.session import AgentSession as _Session
                if _Session._EXAM_INFO_MAX_CHARS is not None:
                    import os as _os
                    raw_size = _os.path.getsize(path)
                    # Use a conservative byte-to-char estimate (1.5×) to avoid
                    # a full parse just for the size check.
                    if raw_size > _Session._EXAM_INFO_MAX_CHARS * 1.5:
                        if hasattr(self, "_settings_status_var"):
                            self._settings_status_var.set(
                                self._t("exam_info_too_large"))
            except Exception:
                pass

    def _on_clear_exam_info(self) -> None:
        self._exam_info_path_var.set("")
        if hasattr(self, "_exam_info_path_label"):
            self._exam_info_path_label.configure(foreground="gray")

    def _on_pick_workspace(self) -> None:
        folder = filedialog.askdirectory(title=self._t("pick_workspace_title"))
        if folder:
            self._workspace_var.set(folder)
            self._refresh_workspace_label()

    def _on_reset_workspace(self) -> None:
        self._workspace_var.set("")
        self._refresh_workspace_label()

    def _refresh_workspace_label(self) -> None:
        """Refresh the workspace-path / default-assignment hint controls."""
        if not hasattr(self, "_workspace_label"):
            return
        _path = self._workspace_var.get().strip()
        if _path:
            self._workspace_label.configure(
                text=_path,
                foreground="black",
            )
            if hasattr(self, "_workspace_pick_btn"):
                self._workspace_pick_btn.configure(
                    text=self._t("settings_change_btn")
                )
            if hasattr(self, "_workspace_clear_btn"):
                self._workspace_clear_btn.grid()
        else:
            self._workspace_label.configure(
                text=self._t("settings_workspace_unset"),
                foreground="gray",
            )
            if hasattr(self, "_workspace_pick_btn"):
                self._workspace_pick_btn.configure(
                    text=self._t("settings_set_btn")
                )
            if hasattr(self, "_workspace_clear_btn"):
                self._workspace_clear_btn.grid_remove()

    def _on_add_files(self, doc_type: DocumentType) -> None:
        paths = filedialog.askopenfilenames(
            title=self._t("add_files_dialog_title").format(
                doctype=self._t(f"doctype_{doc_type.value}")),
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
        _MAX_COURSE_NAME = 200
        _raw_course_name = self._course_name_var.get().strip()
        if len(_raw_course_name) > _MAX_COURSE_NAME:
            _raw_course_name = _raw_course_name[:_MAX_COURSE_NAME]
            self._course_name_var.set(_raw_course_name)
            try:
                self._settings_status_var.set(self._t("course_name_too_long"))
            except Exception:  # noqa: BLE001
                pass
        s.course_name    = _raw_course_name
        s.university_name = self._university_var.get().strip()
        s.major          = self._major_var.get().strip()
        s.course_code    = self._course_code_var.get().strip()
        s.professor_name = self._professor_var.get().strip()
        s.semester       = self._semester_var.get().strip()
        s.exam_type      = self._exam_type_var.get()
        s.exam_format    = self._exam_format_var.get()
        s.exam_duration  = self._exam_duration_var.get().strip()
        s.exam_info_path = self._exam_info_path_var.get().strip()
        self._local_model_var.set(
            self._normalize_local_embedding_model(self._local_model_var.get().strip())
        )
        self._local_model_disp_var.set(
            self._local_model_display_label(self._local_model_var.get())
        )

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
            current = os.environ.get(env_var, "")
            if value != current:
                if value:
                    os.environ[env_var] = value
                else:
                    # Empty field → user is clearing the key; remove from env so
                    # subsequent calls correctly fail with "no API key" rather than
                    # silently continuing with the stale old value.
                    os.environ.pop(env_var, None)
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
            local_model = self._normalize_local_embedding_model(
                self._local_model_var.get() or "all-MiniLM-L6-v2"
            )
            self._local_model_var.set(local_model)
            self._local_model_disp_var.set(
                self._local_model_display_label(local_model)
            )
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
        # Guard: do not mutate session state while a background thread holds a
        # reference to it (indexing, chat, or attachment copy still running).
        # Mutating os.environ keys or session fields mid-flight can produce
        # inconsistent state in the running operation.
        if getattr(self, "_is_busy", False):
            try:
                self._settings_status_var.set(
                    self._t("busy_cannot_apply")
                )
            except Exception:  # noqa: BLE001
                pass
            return

        _prev_exam_info_path = self._session.exam_info_path
        self._sync_session_from_vars()

        # M-6: Validate exam_info_path — warn (but do not block Apply) if the
        # file is set but no longer accessible on disk.
        _exam_path = self._session.exam_info_path
        if _exam_path and (not Path(_exam_path).exists() or not Path(_exam_path).is_file()):
            try:
                self._settings_status_var.set(
                    self._t("exam_file_not_found").format(path=_exam_path))
            except Exception:  # noqa: BLE001
                pass  # dialog destroyed between check and set — harmless

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

        self._cleanup_stale_exam_info_copy(
            _prev_exam_info_path,
            self._session.exam_info_path,
            self._session.workspace_folder,
        )

        # ── Copy exam info file into workspace ────────────────────────────────
        # Store a workspace-local copy so the session remains self-contained even
        # if the original file is moved, renamed, or deleted by the user later.
        # Superseded workspace-local copies are cleaned up above when the field
        # is changed or cleared, so only the current managed exam-info copy
        # remains inside the session workspace.
        # Only copy when: (a) a file is selected, (b) workspace is committed, and
        # (c) the current path is NOT already inside the workspace (avoid re-copy).
        # The copy is performed in a background thread to avoid blocking the main
        # thread with large PDF files (chunked SHA-256 comparison + shutil.copy2
        # can take several seconds for a 50 MB+ file on a slow disk).
        _exam_src = self._session.exam_info_path
        if _exam_src and self._session.workspace_folder:
            _src_path = Path(_exam_src)
            _ws_folder = self._session.workspace_folder
            _exam_uploads = _ws_folder / ".uacragent" / "uploads" / "exam_info"
            # is_relative_to() on resolved paths is separator-agnostic so this
            # works correctly on Windows (where filedialog returns forward-slash
            # paths but str(Path) uses backslashes) and also handles
            # case differences on case-insensitive file systems.
            if _src_path.exists() and not _src_path.resolve().is_relative_to(
                _ws_folder.resolve()
            ):
                import shutil as _shutil, hashlib as _hashlib, threading as _threading

                def _file_sha256(p: Path) -> bytes:
                    h = _hashlib.sha256()
                    with p.open("rb") as _f:
                        for _chunk in iter(lambda: _f.read(65536), b""):
                            h.update(_chunk)
                    return h.digest()

                def _do_copy(
                    src: Path = _src_path,
                    uploads_dir: Path = _exam_uploads,
                    session=self._session,
                ) -> None:
                    try:
                        uploads_dir.mkdir(parents=True, exist_ok=True)
                        dest = uploads_dir / src.name
                        counter = 1
                        while dest.exists() and _file_sha256(dest) != _file_sha256(src):
                            if counter > 1_000:
                                import logging as _logging
                                _logging.getLogger(__name__).warning(
                                    "Exam info copy: exceeded 1 000 collision candidates "
                                    "for '%s'; aborting copy.", src.name)
                                return
                            dest = uploads_dir / f"{src.stem}_{counter}{src.suffix}"
                            counter += 1
                        if not dest.exists():
                            # Guard: refuse to copy a symlink.  shutil.copy2
                            # follows symlinks, so copying one would write the
                            # symlink target's content under the workspace name.
                            if src.is_symlink():
                                raise ValueError(
                                    f"Refusing to copy exam info file: "
                                    f"'{src}' is a symlink."
                                )
                            _shutil.copy2(str(src), str(dest))
                        dest_str = str(dest)
                        # Update session + UI from the main thread.
                        # Guard against session switches: if the user navigated
                        # to a different session while the copy ran, discard the
                        # stale result rather than corrupting the new session.
                        def _apply(
                            _dest=dest_str,
                            _session=session,
                        ) -> None:
                            if self._session is not _session:
                                return  # user switched sessions — discard
                            _session.exam_info_path = _dest
                            try:
                                self._exam_info_path_var.set(_dest)
                                _session._exam_info_cache = None  # noqa: SLF001
                                self._save_current_session()
                            except Exception:  # noqa: BLE001
                                pass
                        try:
                            self.after(0, _apply)
                        except Exception:  # noqa: BLE001
                            pass
                    except Exception as exc:  # noqa: BLE001
                        import logging as _logging
                        _logging.getLogger(__name__).warning(
                            "Could not copy exam info file to workspace: %s", exc)
                        # Surface the failure in the settings status bar so the
                        # user knows exam info is still pointing to the original
                        # path (not a workspace-local copy) and may break if the
                        # original file is moved or deleted.
                        def _show_copy_error(
                            _session=session,
                        ) -> None:
                            if self._session is not _session:
                                return
                            if hasattr(self, "_settings_status_var"):
                                self._settings_status_var.set(
                                    self._t("exam_copy_failed"))
                        try:
                            self.after(0, _show_copy_error)
                        except Exception:  # noqa: BLE001
                            pass

                _threading.Thread(target=_do_copy, daemon=True).start()

        self._save_current_session()
        self._refresh_session_list()
        self._start_indexing(show_error_dialog=True)
