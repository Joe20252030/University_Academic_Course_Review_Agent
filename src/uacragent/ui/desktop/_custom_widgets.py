"""Reusable custom tkinter widgets for the UACRAgent desktop UI.

Provides
--------
draw_rounded_rect
    Helper that draws a smooth rounded rectangle on a ``tk.Canvas``.

AutoHideScrollbar
    A thin pill-shaped canvas overlay that appears on scroll and hides
    automatically after a short idle period — the modern "overlay
    scrollbar" pattern used by macOS, iOS, and most contemporary UIs.

_RoundedChip
    A ``tk.Canvas``-based clickable chip/button with genuine rounded
    corners — works on macOS where ``tk.Button``/``tk.Label`` show
    native Aqua chrome regardless of ``bg``/``relief`` settings.

_SidebarIcon
    A ``tk.Canvas``-based toolbar icon that draws a sidebar-panel symbol
    (rectangle + left strip), used for the sidebar toggle button.

_SessionItemFrame
    A single row in the custom session list — shows name + date with
    hover-reveal rename/delete action icons.  Selected/hovered items
    display a rounded-rectangle highlight (not a plain rectangular fill).

CustomSessionList
    A scrollable canvas-based list of ``_SessionItemFrame`` items that
    replaces the legacy ``tk.Listbox`` in the session sidebar.
"""
from __future__ import annotations

from pathlib import Path
import tkinter as tk


# ---------------------------------------------------------------------------
# Drawing helper
# ---------------------------------------------------------------------------

def draw_left_rounded_rect(
    canvas: tk.Canvas,
    x1: float, y1: float,
    x2: float, y2: float,
    r: float,
    n: int = 14,
    **kw,
) -> int:
    """Draw a rectangle that is rounded only on the left side.

    The right edge (x2) stays perfectly straight.  The top-left and
    bottom-left corners are drawn as smooth arcs with radius *r*.
    Uses explicit arc points (``smooth=False``) for pixel-exact corners.

    Polygon winds clockwise:
      top-right → bottom-right → bottom-left arc → left edge up →
      top-left arc → top edge back to start.
    """
    import math
    r = max(0.0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts: list[float] = []

    # Top-right corner — square
    pts += [x2, y1]

    # Bottom-right corner — square
    pts += [x2, y2]

    # Bottom-left arc: sweep from 90° → 180°
    #   start  (90°):  (x1+r, y2)      — bottom edge just before corner
    #   end   (180°):  (x1,   y2-r)    — left edge just below corner
    cx, cy = x1 + r, y2 - r
    for i in range(n + 1):
        a = math.radians(90 + 90 * i / n)
        pts += [cx + r * math.cos(a), cy + r * math.sin(a)]

    # Top-left arc: sweep from 180° → 270°
    #   start (180°):  (x1,   y1+r)    — left edge just above corner
    #   end   (270°):  (x1+r, y1)      — top edge just after corner
    cx, cy = x1 + r, y1 + r
    for i in range(n + 1):
        a = math.radians(180 + 90 * i / n)
        pts += [cx + r * math.cos(a), cy + r * math.sin(a)]

    # Polygon auto-closes (x1+r, y1) → (x2, y1) along the top edge.
    return canvas.create_polygon(pts, smooth=False, **kw)


def draw_right_rounded_rect(
    canvas: tk.Canvas,
    x1: float, y1: float,
    x2: float, y2: float,
    r: float,
    n: int = 14,
    **kw,
) -> int:
    """Draw a rectangle that is rounded only on the right side.

    The left edge (x1) stays perfectly straight.  The top-right and
    bottom-right corners are drawn as smooth arcs with radius *r*.
    Uses explicit arc points (``smooth=False``) so the left corners are
    pixel-perfect squares and no B-spline bleed-over occurs.

    Parameters
    ----------
    canvas:  Target canvas widget.
    x1, y1: Top-left corner (inclusive).
    x2, y2: Bottom-right corner (inclusive).
    r:       Corner radius for the right-side corners.
    n:       Number of arc segments (higher = smoother, default 14).
    **kw:    Any ``canvas.create_polygon`` keyword args
             (e.g. ``fill``, ``outline``, ``width``, ``tags``).
    """
    import math
    r = max(0.0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts: list[float] = []

    # Top-left corner — straight (square)
    pts += [x1, y1]

    # Top-right arc: sweep from 270° (top of arc) to 360°/0° (right of arc)
    cx, cy = x2 - r, y1 + r
    for i in range(n + 1):
        a = math.radians(270 + 90 * i / n)
        pts += [cx + r * math.cos(a), cy + r * math.sin(a)]

    # Bottom-right arc: sweep from 0° to 90°
    cx, cy = x2 - r, y2 - r
    for i in range(n + 1):
        a = math.radians(90 * i / n)
        pts += [cx + r * math.cos(a), cy + r * math.sin(a)]

    # Bottom-left corner — straight (square); polygon auto-closes along left edge
    pts += [x1, y2]

    return canvas.create_polygon(pts, smooth=False, **kw)


def draw_rounded_rect(
    canvas: tk.Canvas,
    x1: float, y1: float,
    x2: float, y2: float,
    r: float,
    **kw,
) -> int:
    """Draw a smooth rounded rectangle on *canvas* and return its item id.

    Uses a 12-point polygon with ``smooth=True`` — tkinter renders this as
    a smooth B-spline, which looks nicer than arc+line combinations.

    Parameters
    ----------
    canvas:  Target canvas widget.
    x1, y1: Top-left corner (inclusive).
    x2, y2: Bottom-right corner (inclusive).
    r:       Corner radius in pixels.
    **kw:    Any ``canvas.create_polygon`` keyword args
             (e.g. ``fill``, ``outline``, ``width``, ``tags``).
    """
    r = max(0.0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [
        x1 + r, y1,    x2 - r, y1,
        x2,     y1,    x2,     y1 + r,
        x2,     y2 - r, x2,   y2,
        x2 - r, y2,    x1 + r, y2,
        x1,     y2,    x1,     y2 - r,
        x1,     y1 + r, x1,   y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


# ---------------------------------------------------------------------------
# AutoHideScrollbar
# ---------------------------------------------------------------------------

class AutoHideScrollbar:
    """A thin pill-shaped scrollbar that overlays its parent.

    The scrollbar is drawn on a ``tk.Canvas`` that is ``place()``d over the
    right (vertical) or bottom (horizontal) edge of *parent*.  It is
    **always visible** whenever the content overflows (lo > 0 or hi < 1)
    and hidden automatically when all content fits in the viewport — so
    users always have a clear scroll position indicator but no permanent
    empty-track decoration.

    Usage::

        frame = tk.Frame(parent)
        text  = tk.Text(frame, ...)
        text.grid(row=0, column=0, sticky="nsew")

        vsb = AutoHideScrollbar(frame, orient="vertical",
                                color="#9aa5be", bg="#ffffff")
        text.configure(yscrollcommand=vsb.set)

    Pass ``bg`` matching the content background so the canvas blends in
    and only the coloured pill is visible — no track strip.

    When the application theme changes, call :meth:`update_style` so the
    indicator colour stays in sync.
    """

    # ── Appearance tunables ──────────────────────────────────────────────
    BAR_WIDTH    = 5      # scrollbar pill thickness  (px)
    BAR_MARGIN   = 2      # gap between pill and canvas edge (px)
    CORNER_R     = 3      # pill end-cap corner radius (px)
    MIN_THUMB_PX = 22     # minimum thumb length (px)

    def __init__(
        self,
        parent: tk.Widget,
        orient: str = "vertical",
        color: str = "#9aa5be",
        bg: str    = "#ffffff",
    ) -> None:
        self._parent  = parent
        self._orient  = orient
        self._color   = color
        self._bg      = bg
        self._lo: float = 0.0
        self._hi: float = 1.0
        self._visible   = False

        total = self.BAR_WIDTH + self.BAR_MARGIN * 2
        cv_kw: dict = dict(highlightthickness=0, bd=0, cursor="arrow")
        if orient == "vertical":
            cv_kw["width"] = total
        else:
            cv_kw["height"] = total

        self._cv = tk.Canvas(parent, **cv_kw)
        parent.bind("<Configure>", self._on_parent_resize, add="+")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set(self, lo: str, hi: str) -> None:
        """``yscrollcommand`` / ``xscrollcommand`` callback.

        Show the thumb whenever content overflows; hide it when all
        content fits in view.  No timer-based auto-hiding — the indicator
        stays visible as long as there is something to scroll.
        """
        self._lo = float(lo)
        self._hi = float(hi)
        if self._lo <= 0.0 and self._hi >= 1.0:
            # All content fits — hide the indicator
            if self._visible:
                self._cv.place_forget()
                self._visible = False
        else:
            # Content overflows — show (or keep showing) the indicator
            self._show()

    def update_style(self, color: str, bg: str) -> None:
        """Re-apply theme colours — call after every theme switch."""
        self._color = color
        self._bg    = bg
        self._cv.configure(bg=bg)
        if self._visible:
            self._draw_thumb()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_parent_resize(self, _event) -> None:
        if self._visible:
            self._place()
            self._draw_thumb()

    def _place(self) -> None:
        """``place()`` the canvas over the appropriate edge of *parent*."""
        total = self.BAR_WIDTH + self.BAR_MARGIN * 2
        self._cv.configure(bg=self._bg)
        if self._orient == "vertical":
            self._cv.place(
                relx=1.0, x=-total,
                rely=0.0, relheight=1.0,
                width=total,
            )
        else:
            self._cv.place(
                relx=0.0, relwidth=1.0,
                rely=1.0, y=-total,
                height=total,
            )
        # Canvas overrides lift/tkraise to mean tag_raise (canvas item).
        # Call the Tk 'raise' window-manager command directly to raise the
        # overlay canvas widget above its siblings.
        self._cv.tk.call("raise", self._cv._w)

    def _show(self) -> None:
        if not self._visible:
            self._place()
            self._visible = True
        self._draw_thumb()

    def _draw_thumb(self) -> None:
        """Repaint the pill indicator to reflect the current scroll position."""
        self._cv.delete("thumb")
        m  = self.BAR_MARGIN
        bw = self.BAR_WIDTH

        if self._orient == "vertical":
            h = self._cv.winfo_height()
            if h <= 1:
                # Widget not yet laid out — retry after a short delay
                self._parent.after(50, self._draw_thumb)
                return
            thumb_h = max(self.MIN_THUMB_PX, int((self._hi - self._lo) * h))
            raw_y   = int(self._lo * h)
            thumb_y = max(2, min(h - thumb_h - 2, raw_y))
            x1, y1 = m,      thumb_y
            x2, y2 = m + bw, thumb_y + thumb_h
        else:
            w = self._cv.winfo_width()
            if w <= 1:
                self._parent.after(50, self._draw_thumb)
                return
            thumb_w = max(self.MIN_THUMB_PX, int((self._hi - self._lo) * w))
            raw_x   = int(self._lo * w)
            thumb_x = max(2, min(w - thumb_w - 2, raw_x))
            x1, y1 = thumb_x,           m
            x2, y2 = thumb_x + thumb_w, m + bw

        if x2 <= x1:
            x2 = x1 + 2
        if y2 <= y1:
            y2 = y1 + 2

        draw_rounded_rect(
            self._cv, x1, y1, x2, y2,
            r=min(self.CORNER_R, (x2 - x1) // 2, (y2 - y1) // 2),
            fill=self._color, outline="", tags="thumb",
        )


# ---------------------------------------------------------------------------
# _RoundedChip
# ---------------------------------------------------------------------------

class _RoundedChip(tk.Canvas):
    """Canvas-based clickable chip with genuine rounded corners.

    ``tk.Label`` and ``tk.Button`` show native Aqua chrome on macOS and
    therefore cannot be styled with ``bg``/``relief``.  This widget draws
    the fill and border itself via ``draw_rounded_rect``, giving a
    consistent pill shape on every platform.

    Usage::

        chip = _RoundedChip(
            parent, text="Summarise",
            chip_bg="#e8ecf5", chip_fg="#1a2744",
            parent_bg="#ffffff",        # must match the parent's bg
            font=("TkDefaultFont", 11),
            command=lambda: ...,
        )
        chip.pack(side="left", padx=(0, 6))

    Call :meth:`update_style` after a theme change and :meth:`set_text`
    (or ``configure(text=…)``) after a language change.
    """

    CORNER_R = 8

    def __init__(
        self,
        parent: tk.Widget,
        text: str,
        chip_bg: str,
        chip_fg: str,
        parent_bg: str,
        font=("TkDefaultFont", 11),
        padx: int = 10,
        pady: int = 5,
        command=None,
        hover_bg: str | None = None,
        outline: str = "",
        outline_width: int = 0,
        disabled_bg: str = "#c8c8c8",
        disabled_fg: str = "#888888",
        text_anchor: str = "center",
    ) -> None:
        self._text          = text
        self._chip_bg       = chip_bg
        self._chip_fg       = chip_fg
        self._hover_bg      = hover_bg or chip_bg
        self._font          = font
        self._padx          = padx
        self._pady          = pady
        self._command       = command
        self._outline       = outline
        self._outline_width = outline_width
        self._disabled_bg   = disabled_bg
        self._disabled_fg   = disabled_fg
        self._hovered       = False
        self._enabled       = True
        self._text_anchor   = text_anchor

        # Measure required canvas size via a throw-away Label
        _tmp = tk.Label(parent, text=text, font=font)
        _tmp.update_idletasks()
        _tw = _tmp.winfo_reqwidth()
        _th = _tmp.winfo_reqheight()
        _tmp.destroy()

        _cw = _tw + padx * 2
        _ch = _th + pady * 2

        super().__init__(
            parent,
            width=_cw, height=_ch,
            bg=parent_bg,
            highlightthickness=0, bd=0,
            cursor="hand2",
        )

        self.bind("<Configure>", lambda _e: self._redraw())
        self.bind("<Enter>",     lambda _e: self._on_enter())
        self.bind("<Leave>",     lambda _e: self._on_leave())
        self.bind("<Button-1>",  lambda _e: self._on_click())

    # ------------------------------------------------------------------
    # Internal event handlers
    # ------------------------------------------------------------------

    def _on_enter(self) -> None:
        self._hovered = True
        self._redraw()

    def _on_leave(self) -> None:
        self._hovered = False
        self._redraw()

    def _on_click(self) -> None:
        if self._enabled and self._command:
            self._command()

    def _redraw(self) -> None:
        self.delete("chip")
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= 1 or h <= 1:
            self.after(20, self._redraw)
            return
        if not self._enabled:
            fill    = self._disabled_bg
            text_fg = self._disabled_fg
        elif self._hovered:
            fill    = self._hover_bg
            text_fg = self._chip_fg
        else:
            fill    = self._chip_bg
            text_fg = self._chip_fg
        r = min(self.CORNER_R, w // 2, h // 2)
        # Inset by 1 px so the outline stroke (width=1 straddles the path
        # centre by ±0.5 px) is never clipped by the canvas boundary.
        draw_rounded_rect(
            self, 1, 1, w - 1, h - 1, r=r,
            fill=fill,
            outline=self._outline,
            width=self._outline_width,
            tags="chip",
        )
        if self._text_anchor == "w":
            self.create_text(
                self._padx, h // 2,
                text=self._text,
                fill=text_fg,
                font=self._font,
                anchor="w",
                tags="chip",
            )
        else:
            self.create_text(
                w // 2, h // 2,
                text=self._text,
                fill=text_fg,
                font=self._font,
                tags="chip",
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resize_to_fit(self) -> None:
        """Resize the canvas so the current text + font fit without clipping.

        Called whenever the label text or font changes after construction so
        the chip always expands (or contracts) to exactly hold its content.
        ``update_idletasks`` is called after ``configure`` so the geometry
        manager processes the new size before ``_redraw`` queries
        ``winfo_width``/``winfo_height``.
        """
        try:
            parent_widget = self.nametowidget(self.winfo_parent())
        except Exception:
            parent_widget = self

        _tmp = tk.Label(parent_widget, text=self._text, font=self._font)
        _tmp.update_idletasks()
        _tw = _tmp.winfo_reqwidth()
        _th = _tmp.winfo_reqheight()
        _tmp.destroy()

        _cw = max(_tw + self._padx * 2, 1)
        _ch = max(_th + self._pady * 2, 1)
        tk.Canvas.configure(self, width=_cw, height=_ch)
        # Flush geometry so winfo_width/height return the new values
        # immediately when _redraw() runs next.
        self.update_idletasks()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_text(self, text: str) -> None:
        """Update the chip label, resize the canvas to fit, and redraw."""
        self._text = text
        self._resize_to_fit()
        self._redraw()

    def set_state(self, enabled: bool) -> None:
        """Enable or disable the chip (disabled = dimmed, non-clickable)."""
        self._enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")
        self._redraw()

    def configure(self, **kw) -> None:
        """Override so ``configure(text=…)`` calls :meth:`set_text`."""
        if "text" in kw:
            self.set_text(kw.pop("text"))
        if kw:
            tk.Canvas.configure(self, **kw)

    def update_style(
        self,
        text: str | None        = None,
        chip_bg: str | None     = None,
        chip_fg: str | None     = None,
        hover_bg: str | None    = None,
        parent_bg: str | None   = None,
        outline: str | None     = None,
        outline_width: int | None = None,
        font=None,
        text_anchor: str | None = None,
    ) -> None:
        """Re-apply theme colours / font — call after every theme switch."""
        if text          is not None: self._text          = text
        if chip_bg       is not None: self._chip_bg       = chip_bg
        if chip_fg       is not None: self._chip_fg       = chip_fg
        if hover_bg      is not None: self._hover_bg      = hover_bg
        if outline       is not None: self._outline       = outline
        if outline_width is not None: self._outline_width = outline_width
        if font          is not None: self._font          = font
        if text_anchor   is not None: self._text_anchor   = text_anchor
        if parent_bg     is not None:
            tk.Canvas.configure(self, bg=parent_bg)
        # Resize the canvas whenever content dimensions may have changed
        # (font or text updated) so larger fonts are never clipped.
        if font is not None or text is not None:
            self._resize_to_fit()
        self._redraw()


# ---------------------------------------------------------------------------
# _SidebarIcon
# ---------------------------------------------------------------------------

class _SidebarIcon(tk.Canvas):
    """Toolbar toggle button drawn as a sidebar-panel icon.

    Renders a small rounded rectangle (the "app window") with a coloured
    vertical strip on the left (the "sidebar").  When the sidebar is
    visible the strip is filled; when hidden it is empty.  Clicking calls
    *command*.

    The widget background is set to ``colors["window_bg"]`` so it blends
    into the global toolbar with no visible canvas border.
    """

    ICON_W  = 22   # icon drawing width  (px)
    ICON_H  = 17   # icon drawing height (px)
    PANEL_W = 7    # width of the left sidebar strip inside the icon

    def __init__(
        self,
        parent: tk.Widget,
        command,
        colors: dict,
        parent_bg: str | None = None,
    ) -> None:
        self._colors          = colors
        self._command         = command
        self._sidebar_visible = True
        self._hovered         = False
        # When set, the canvas bg uses this colour instead of window_bg so the
        # icon blends seamlessly into a parent that is not window_bg (e.g. the
        # white text_bg card when the toggle lives inside the unified card).
        self._parent_bg       = parent_bg

        _wbg = parent_bg if parent_bg is not None else colors.get("window_bg", "#ffffff")
        super().__init__(
            parent,
            width  = self.ICON_W + 10,
            height = self.ICON_H + 10,
            bg     = _wbg,
            highlightthickness=0, bd=0,
            cursor="hand2",
        )

        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Enter>",     lambda _e: self._on_enter())
        self.bind("<Leave>",     lambda _e: self._on_leave())
        self.bind("<Button-1>",  lambda _e: self._on_click())

    # ------------------------------------------------------------------
    # Internal event handlers
    # ------------------------------------------------------------------

    def _on_enter(self) -> None:
        self._hovered = True
        self._draw()

    def _on_leave(self) -> None:
        self._hovered = False
        self._draw()

    def _on_click(self) -> None:
        if self._command:
            self._command()

    def _draw(self) -> None:
        self.delete("icon")
        cw = self.winfo_width()
        ch = self.winfo_height()
        if cw <= 1 or ch <= 1:
            self.after(20, self._draw)
            return

        c       = self._colors
        fg_col  = c.get("lb_fg",       "#1a2744")
        wbg_col = c.get("window_bg",   "#f0f3f9")
        sbg_col = c.get("sidebar_bg",  "#e8ecf5")
        hov_col = c.get("lb_hover_bg", "#dfe4f0")

        # Canvas bg matches parent_bg (if set) or window_bg — no permanent box.
        # The hover highlight is drawn as a rounded rect ON the canvas so only
        # hovering produces a visible colour change.
        _cv_bg = self._parent_bg if self._parent_bg is not None else wbg_col
        self.configure(bg=_cv_bg)

        # 1. Hover highlight — rounded rect behind the icon (hover only)
        if self._hovered:
            draw_rounded_rect(
                self, 1, 1, cw - 1, ch - 1, r=6,
                fill=hov_col, outline="",
                tags="icon",
            )

        # Icon bounding box, centred in the canvas
        IW, IH = self.ICON_W, self.ICON_H
        ox = (cw - IW) // 2
        oy = (ch - IH) // 2
        r  = 3   # corner radius for the outer frame rect

        # 2. Outer frame (rounded rect, window bg fill + subtle border)
        draw_rounded_rect(
            self, ox, oy, ox + IW, oy + IH, r=r,
            fill=wbg_col, outline=fg_col, width=1,
            tags="icon",
        )

        # 3. Left sidebar strip fill (only when sidebar is visible)
        strip_x2 = ox + self.PANEL_W
        if self._sidebar_visible:
            self.create_rectangle(
                ox + 1, oy + 1, strip_x2, oy + IH - 1,
                fill=sbg_col, outline="", tags="icon",
            )

        # 4. Vertical divider between sidebar strip and main content
        self.create_line(
            strip_x2, oy + 1, strip_x2, oy + IH - 1,
            fill=fg_col, width=1, tags="icon",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_sidebar_visible(self, visible: bool) -> None:
        """Update the icon to reflect sidebar state and redraw."""
        self._sidebar_visible = visible
        self._draw()

    def update_colors(self, colors: dict, parent_bg: str | None = None) -> None:
        """Re-apply theme colours — call after every theme switch."""
        self._colors = colors
        if parent_bg is not None:
            self._parent_bg = parent_bg
        _bg = self._parent_bg if self._parent_bg is not None else colors.get("window_bg", "#ffffff")
        tk.Canvas.configure(self, bg=_bg)
        self._draw()


# ---------------------------------------------------------------------------
# _SessionItemFrame
# ---------------------------------------------------------------------------

class _SessionItemFrame(tk.Frame):
    """A single session entry in the custom session list.

    Shows the session name and date sub-label on the left.  On hover (or
    when selected) a single ``⋯`` button slides in from the right; clicking
    it opens a small popup menu with Rename and Delete actions so the row
    stays clean and uncluttered by default.

    Selected and hovered items are highlighted with a *rounded* rectangle
    rather than a plain rectangular fill.  This is achieved via a
    ``tk.Canvas`` (``_bg_cv``) placed behind all other children:

    * Frame ``bg`` is always set to ``lb_bg`` (the list background) so the
      frame corners reveal the list background — making the item look
      "transparent" at the corners.
    * ``_bg_cv`` covers the full frame area via ``place()``.  Its own ``bg``
      is also ``lb_bg``.  When hovered / selected, a rounded-rect polygon
      is drawn on the canvas in the highlight colour — the canvas corners
      (outside the rounded polygon) show ``lb_bg``, giving a natural
      rounded-corner look.
    * All child labels are created *after* the canvas so they appear on
      top; their ``bg`` is updated to match the highlight fill so the
      label backgrounds match the canvas fill.
    """

    CORNER_R = 8   # selection rounded-rect corner radius

    def __init__(
        self,
        parent: tk.Widget,
        name: str,
        on_select,
        on_rename,
        on_delete,
        idx: int,
        colors: dict,
        rename_label: str = "✏  Rename",
        delete_label: str = "🗑  Delete",
    ) -> None:
        self._colors = colors
        self._idx = idx
        self._on_select = on_select
        self._on_rename = on_rename
        self._on_delete = on_delete
        self._selected  = False
        self._rename_label = rename_label
        self._delete_label = delete_label

        lb_bg = colors.get("lb_bg", "#e8ecf5")
        # Frame bg = list background so frame corners "reveal" lb_bg
        super().__init__(parent, bg=lb_bg, cursor="hand2")
        # NOTE: no pady here — internal padding breaks the rounded-rect
        # illusion (the bg_cv relheight=1 would not cover the padded strips,
        # producing rectangular strips at the top and bottom).

        self._menu_open = False   # True while the ⋯ popup menu is visible

        # ── Background canvas (created FIRST so it sits below all labels) ──
        # Canvas bg = lb_bg; a rounded-rect polygon is drawn on it whenever
        # the item is hovered or selected.  Corners outside the polygon show
        # lb_bg, producing the rounded-corner illusion.
        self._bg_cv = tk.Canvas(self, bg=lb_bg, highlightthickness=0, bd=0)
        self._bg_cv.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._bg_cv.bind("<Configure>", lambda _e: self._redraw_bg())
        self._current_fill = lb_bg   # updated by _set_bg
        self._hovered      = False

        # ── Labels (created AFTER canvas so they appear on top) ──────────

        # Right: ⋯ button — packed RIGHT first so space is always reserved and
        # the name label clips naturally before reaching it.
        # Lives directly in `self` (no intermediate frame) so there is exactly
        # one pack geometry context — eliminating the sub-frame anchor offset
        # that was causing the ⋯ to misalign vertically.
        # pady=4 matches _label_name, so both widgets share identical external
        # padding and sit at the same vertical position within the row.
        self._btn_more = tk.Label(
            self, text="⋯",
            bg=lb_bg, fg=lb_bg,   # invisible initially (fg == bg)
            font=("TkDefaultFont", 12),
            cursor="hand2",
            padx=4,
        )
        self._btn_more.pack(side="right", padx=(0, 4), pady=4)
        self._btn_more.bind("<Button-1>", self._on_more_click)

        # Left: name label — fills remaining space; text clips naturally
        # before the always-reserved ⋯ area.
        self._label_name = tk.Label(
            self, text=f"  {name}",
            bg=lb_bg, fg=colors.get("lb_fg", "#1a2744"),
            font=("TkDefaultFont", 12),
            anchor="w",
        )
        self._label_name.pack(side="left", fill="x", expand=True, padx=(2, 0), pady=4)

        # Bind hover + click on every part of the row (including the canvas)
        for w in (self, self._bg_cv, self._label_name, self._btn_more):
            w.bind("<Enter>",    self._on_enter,  add="+")
            w.bind("<Leave>",    self._on_leave,  add="+")
            w.bind("<Button-1>", self._on_click,  add="+")

    # ------------------------------------------------------------------
    # Background canvas helpers
    # ------------------------------------------------------------------

    def _redraw_bg(self) -> None:
        """Repaint the rounded-rect highlight on ``_bg_cv``."""
        lb_bg  = self._colors.get("lb_bg",       "#e8ecf5")
        border = self._colors.get("input_border", "#cdd4e8")
        self._bg_cv.configure(bg=lb_bg)
        self._bg_cv.delete("sel")
        w = self._bg_cv.winfo_width()
        h = self._bg_cv.winfo_height()
        if w <= 2 or h <= 2:
            return
        if self._current_fill != lb_bg:
            draw_rounded_rect(
                self._bg_cv, 1, 1, w - 1, h - 1,
                r=self.CORNER_R,
                fill=self._current_fill, outline="",
                tags="sel",
            )

    # ------------------------------------------------------------------
    # ⋯ button visibility helper
    # ------------------------------------------------------------------

    def _update_btn_more_fg(self) -> None:
        """Make ⋯ visible on hover, selection, or while its menu is open."""
        if self._hovered or self._selected or self._menu_open:
            # Use a fg colour that contrasts with the current background:
            #   selected  → bg is lb_sel_bg (dark blue) → use lb_sel_fg (white)
            #   hover only → bg is lb_hover_bg (light)  → use lb_fg (dark)
            if self._selected:
                fg = self._colors.get("lb_sel_fg", "#ffffff")
            else:
                fg = self._colors.get("lb_fg", "#1a2744")
        else:
            fg = self._current_fill   # matches background → invisible
        self._btn_more.configure(fg=fg)

    # ------------------------------------------------------------------
    # Hover helpers
    # ------------------------------------------------------------------

    def _on_enter(self, event=None) -> None:
        self._hovered = True
        if not self._selected:
            hover = self._colors.get("lb_hover_bg", "#dfe4f0")
            self._set_bg(hover)
        self._update_btn_more_fg()

    def _on_leave(self, event=None) -> None:
        # While the ⋯ popup menu is open the mouse is over the native menu
        # widget (which has no Tk identity on macOS), so Leave events fire
        # spuriously.  Suppress all state changes until the menu closes.
        if self._menu_open:
            return
        # Only trigger when the pointer has genuinely left this widget tree
        if event is not None:
            widget_under = self.winfo_containing(event.x_root, event.y_root)
            if widget_under is not None and self._is_inside(widget_under):
                return
        self._hovered = False
        if not self._selected:
            bg = self._colors.get("lb_bg", "#e8ecf5")
            self._set_bg(bg)
        self._update_btn_more_fg()

    def _is_inside(self, widget: tk.Widget) -> bool:
        """Return True if *widget* is self or a descendant of self."""
        try:
            w = widget
            while True:
                if w == self:
                    return True
                parent_name = w.winfo_parent()
                if not parent_name:
                    break
                w = w.nametowidget(parent_name)
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------
    # Click handlers
    # ------------------------------------------------------------------

    def _on_click(self, event=None) -> None:
        self._on_select(self._idx)

    def _on_more_click(self, event=None) -> None:
        """Show the popup context menu (Rename / Delete) at the cursor."""
        # Mark the menu as open so ⋯ stays visible until it closes.
        self._menu_open = True
        self._update_btn_more_fg()

        menu = tk.Menu(self.winfo_toplevel(), tearoff=0)
        menu.add_command(
            label=self._rename_label,
            command=lambda: self._on_rename(self._idx),
        )
        menu.add_command(
            label=self._delete_label,
            command=lambda: self._on_delete(self._idx),
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

        # Poll until the menu widget is destroyed to reset _menu_open.
        # Binding <Unmap> is unreliable on macOS: Tk unmaps the Tk-side menu
        # widget the instant the native popup appears (not when it closes), so
        # <Unmap> would fire immediately, cancelling the flag before the user
        # even sees the menu.  winfo_exists() is cross-platform and accurate.
        def _poll_closed() -> None:
            try:
                if menu.winfo_exists():
                    self.after(50, _poll_closed)
                    return
            except Exception:
                pass
            # Menu is gone — reset flag, then apply the leave behaviour that
            # was suppressed while the menu was open (mouse may now be outside).
            self._menu_open = False
            try:
                px = self.winfo_pointerx()
                py = self.winfo_pointery()
                under = self.winfo_containing(px, py)
                if under is None or not self._is_inside(under):
                    # Pointer is outside the row — run normal leave cleanup
                    self._hovered = False
                    if not self._selected:
                        self._set_bg(self._colors.get("lb_bg", "#e8ecf5"))
            except Exception:
                pass
            self._update_btn_more_fg()

        self.after(50, _poll_closed)
        return "break"

    # ------------------------------------------------------------------
    # Selection / theme
    # ------------------------------------------------------------------

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        if selected:
            bg = self._colors.get("lb_sel_bg", "#1b3167")
            fg = self._colors.get("lb_sel_fg", "#ffffff")
        else:
            bg = self._colors.get("lb_bg", "#e8ecf5")
            fg = self._colors.get("lb_fg", "#1a2744")
        self._set_bg(bg)
        self._label_name.configure(fg=fg)
        self._update_btn_more_fg()

    def _set_bg(self, bg: str) -> None:
        """Set the fill colour — updates the canvas rounded rect + all labels."""
        lb_bg = self._colors.get("lb_bg", "#e8ecf5")
        self._current_fill = bg
        # Frame bg stays lb_bg always (reveals rounded corners)
        self.configure(bg=lb_bg)
        self._redraw_bg()
        # Labels' bg matches the fill so they look correct on top of canvas
        self._label_name.configure(bg=bg)
        self._btn_more.configure(bg=bg)
        self._update_btn_more_fg()

    def update_colors(self, colors: dict) -> None:
        self._colors = colors
        was_selected = self._selected
        self.set_selected(was_selected)


# ---------------------------------------------------------------------------
# CustomSessionList
# ---------------------------------------------------------------------------

class CustomSessionList:
    """Scrollable canvas-based session list that replaces tk.Listbox.

    Wraps a ``tk.Canvas`` (with ``AutoHideScrollbar``) containing an inner
    ``tk.Frame`` that holds one ``_SessionItemFrame`` per session record.

    The public API mirrors the minimal subset of ``tk.Listbox`` that the rest
    of the app uses so that callers need minimal changes.
    """

    def __init__(
        self,
        parent: tk.Widget,
        on_select,
        on_rename,
        on_delete,
        colors: dict,
        rename_label: str = "✏  Rename",
        delete_label: str = "🗑  Delete",
    ) -> None:
        self._parent = parent
        self._on_select_cb = on_select
        self._on_rename_cb = on_rename
        self._on_delete_cb = on_delete
        self._colors = colors
        self._rename_label = rename_label
        self._delete_label = delete_label
        self._items: list[_SessionItemFrame] = []
        self._selected_idx: int | None = None

        bg = colors.get("lb_bg", "#e8ecf5")

        # Canvas (the scrollable viewport)
        self._canvas = tk.Canvas(
            parent,
            bg=bg,
            highlightthickness=0, bd=0,
        )

        # Inner scrollable frame
        self._inner = tk.Frame(self._canvas, bg=bg)
        self._inner.columnconfigure(0, weight=1)
        self._inner_id = self._canvas.create_window(0, 0, anchor="nw",
                                                      window=self._inner)

        # Persistent thumb scrollbar — bg matches lb_bg so no track is visible
        self._vsb = AutoHideScrollbar(
            parent, orient="vertical",
            color=colors.get("sb_color", "#9aa5be"),
            bg=bg,   # always use lb_bg so the canvas blends into the list
        )
        self._canvas.configure(yscrollcommand=self._vsb.set)

        # Keep inner frame width in sync with canvas width
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._inner.bind("<Configure>", self._on_inner_configure)

        # Propagate mousewheel from canvas
        self._bind_scroll(self._canvas)

    # ------------------------------------------------------------------
    # Grid delegation (so callers can do self._session_list.grid(...))
    # ------------------------------------------------------------------

    def grid(self, **kw) -> None:
        self._canvas.grid(**kw)

    # ------------------------------------------------------------------
    # Scroll helpers
    # ------------------------------------------------------------------

    def _bind_scroll(self, widget: tk.Widget) -> None:
        import sys
        if sys.platform == "darwin":
            widget.bind("<MouseWheel>", self._on_mousewheel_mac, add="+")
        elif sys.platform.startswith("win"):
            widget.bind("<MouseWheel>", self._on_mousewheel_win, add="+")
        else:
            widget.bind("<Button-4>", self._on_scroll_up, add="+")
            widget.bind("<Button-5>", self._on_scroll_down, add="+")

    def _bounded_scroll(self, units: int) -> None:
        """Scroll by *units*, stopping cleanly at both ends of content.

        No-op when all items fit in the viewport (lo==0, hi==1) so the
        session list never scrolls past its own content.
        """
        try:
            lo, hi = self._canvas.yview()
            if units < 0 and lo <= 0.0:
                return
            if units > 0 and hi >= 1.0:
                return
            self._canvas.yview_scroll(units, "units")
        except Exception:
            pass

    def _on_mousewheel_mac(self, event) -> None:
        self._bounded_scroll(int(-1 * event.delta))

    def _on_mousewheel_win(self, event) -> None:
        self._bounded_scroll(int(-1 * (event.delta / 120)))

    def _on_scroll_up(self, event) -> None:
        self._bounded_scroll(-1)

    def _on_scroll_down(self, event) -> None:
        self._bounded_scroll(1)

    def _on_canvas_configure(self, event=None) -> None:
        w = self._canvas.winfo_width()
        self._canvas.itemconfigure(self._inner_id, width=max(1, w))

    def _on_inner_configure(self, event=None) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    # ------------------------------------------------------------------
    # Public list API
    # ------------------------------------------------------------------

    def set_menu_labels(self, rename: str, delete: str) -> None:
        """Update the Rename/Delete labels shown in each item's popup menu.

        Called by the app whenever the UI language changes so that existing
        items pick up the new strings immediately without a full refresh.
        """
        self._rename_label = rename
        self._delete_label = delete
        for item in self._items:
            item._rename_label = rename
            item._delete_label = delete

    def refresh(self, records: list[dict], active_workspace: "str | None") -> None:
        """Rebuild all list items from *records*; re-select the active session."""
        # Destroy old items
        for item in self._items:
            item.destroy()
        self._items = []
        self._selected_idx = None

        for idx, rec in enumerate(records):
            name = (rec.get("display_name")
                    or rec.get("course_name")
                    or Path(rec.get("workspace", "")).name)

            item = _SessionItemFrame(
                self._inner,
                name=name,
                on_select=self._on_select,
                on_rename=self._on_rename,
                on_delete=self._on_delete,
                idx=idx,
                colors=self._colors,
                rename_label=self._rename_label,
                delete_label=self._delete_label,
            )
            item.grid(row=idx, column=0, sticky="ew", pady=1)
            self._bind_scroll(item)
            for child in item.winfo_children():
                self._bind_scroll(child)
            self._items.append(item)

        # Re-select active session
        if active_workspace:
            active = Path(active_workspace).resolve()
            for i, rec in enumerate(records):
                if Path(rec.get("workspace", "")).resolve() == active:
                    self.select_idx(i)
                    break

    def _on_select(self, idx: int) -> None:
        self.select_idx(idx)
        self._on_select_cb(idx)

    def _on_rename(self, idx: int) -> None:
        self._on_rename_cb(idx)

    def _on_delete(self, idx: int) -> None:
        self._on_delete_cb(idx)

    def select_idx(self, idx: int) -> None:
        """Set the visual selection to *idx*."""
        if self._selected_idx is not None and self._selected_idx < len(self._items):
            self._items[self._selected_idx].set_selected(False)
        self._selected_idx = idx
        if 0 <= idx < len(self._items):
            self._items[idx].set_selected(True)
            # Scroll into view
            self._canvas.update_idletasks()
            item = self._items[idx]
            try:
                y = item.winfo_y()
                h = item.winfo_height()
                canvas_h = self._canvas.winfo_height()
                scroll_top = self._canvas.yview()[0]
                total_h = self._inner.winfo_reqheight()
                if total_h <= 0:
                    return
                frac_top = y / total_h
                frac_bot = (y + h) / total_h
                view_top, view_bot = self._canvas.yview()
                if frac_top < view_top:
                    self._canvas.yview_moveto(frac_top)
                elif frac_bot > view_bot:
                    self._canvas.yview_moveto(max(0, frac_bot - canvas_h / total_h))
            except Exception:
                pass

    def get_selected_idx(self) -> "int | None":
        return self._selected_idx

    def curselection(self) -> tuple:
        """Compatibility shim: returns ``(idx,)`` or ``()``."""
        if self._selected_idx is not None:
            return (self._selected_idx,)
        return ()

    def update_colors(self, colors: dict) -> None:
        self._colors = colors
        bg = colors.get("lb_bg", "#e8ecf5")
        self._canvas.configure(bg=bg)
        self._inner.configure(bg=bg)
        # bg always matches lb_bg so the canvas blends in (no visible track)
        self._vsb.update_style(colors.get("sb_color", "#9aa5be"), bg)
        for item in self._items:
            item.update_colors(colors)
