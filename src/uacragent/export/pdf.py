from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path

from fpdf import FPDF

from uacragent.infra.workspace import WorkspacePaths

# Common system TTF font paths (checked in order; first match wins).
_UNICODE_FONT_CANDIDATES = [
    # macOS
    "/System/Library/Fonts/Supplemental/Arial Unicode MS.ttf",
    "/Library/Fonts/Arial Unicode MS.ttf",
    # Linux (DejaVu, Liberation, Noto)
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    # Windows
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/arialuni.ttf",
]


def _find_unicode_font() -> str | None:
    """Return the path of the first available Unicode TTF font, or None."""
    for path in _UNICODE_FONT_CANDIDATES:
        if Path(path).exists():
            return path
    return None


def _safe_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


class _ReviewPDF(FPDF):
    """FPDF2 subclass that converts simplified Markdown to PDF.

    Uses a Unicode TTF font when one is available on the system so that
    non-ASCII content (Greek letters, accented characters, CJK, etc.) is
    rendered correctly.  Falls back to Helvetica + best-effort
    transliteration when no suitable font is found.
    """

    def __init__(self) -> None:
        super().__init__()
        self.add_page()
        self.set_auto_page_break(auto=True, margin=15)

        unicode_font = _find_unicode_font()
        if unicode_font:
            self.add_font("Unicode", "", unicode_font)
            self.add_font("Unicode", "B", unicode_font)
            self._body_font = "Unicode"
        else:
            self._body_font = "Helvetica"

        self.set_font(self._body_font, size=11)

    # ------------------------------------------------------------------
    def _heading(self, text: str, level: int) -> None:
        sizes = {1: 20, 2: 16, 3: 13}
        self.set_font(self._body_font, style="B", size=sizes.get(level, 12))
        self.ln(4)
        self.multi_cell(0, 8, self._prep(text))
        self.ln(2)
        self.set_font(self._body_font, size=11)

    def _bullet(self, text: str) -> None:
        self.set_x(15)
        self.cell(6, 6, "-")
        self.multi_cell(0, 6, self._prep(text))

    def _numbered(self, text: str, number: str) -> None:
        self.set_x(15)
        self.cell(8, 6, f"{number}")
        self.multi_cell(0, 6, self._prep(text))

    def _paragraph(self, text: str) -> None:
        self.multi_cell(0, 6, self._prep(text))
        self.ln(2)

    def _prep(self, text: str) -> str:
        """Prepare text for output: sanitize only if using the fallback font."""
        if self._body_font == "Helvetica":
            return _sanitize_latin1(text)
        return text

    # ------------------------------------------------------------------
    def add_markdown(self, md_text: str) -> None:
        for line in md_text.splitlines():
            stripped = line.strip()
            if not stripped:
                self.ln(3)
                continue

            if stripped.startswith("### "):
                self._heading(stripped[4:], 3)
            elif stripped.startswith("## "):
                self._heading(stripped[3:], 2)
            elif stripped.startswith("# "):
                self._heading(stripped[2:], 1)
            elif re.match(r"^[-*]\s", stripped):
                self._bullet(stripped[2:])
            elif m := re.match(r"^(\d+)\.\s", stripped):
                self._numbered(re.sub(r"^\d+\.\s", "", stripped), m.group(1))
            else:
                self._paragraph(stripped)


def _sanitize_latin1(text: str) -> str:
    """Transliterate Unicode to latin-1 as faithfully as possible.

    Uses NFKD normalisation to decompose accented characters (e.g. é → e +
    combining accent), then drops combining marks, before finally replacing
    any remaining non-latin-1 characters with '?'.
    """
    # Named replacements for common symbols that normalisation won't handle
    replacements = {
        "‘": "'", "’": "'",
        "“": '"', "”": '"',
        "–": "-", "—": "--",
        "•": "-",
        "…": "...",
        "α": "alpha", "β": "beta", "γ": "gamma",
        "δ": "delta", "μ": "mu", "σ": "sigma",
        "π": "pi", "λ": "lambda", "θ": "theta",
        "∈": "in", "∉": "not in",
        "∀": "for all", "∃": "there exists",
        "∧": "and", "∨": "or", "¬": "not",
        "→": "->", "⇒": "=>",
        "≤": "<=", "≥": ">=",
        "∞": "inf",
        "∑": "sum", "∏": "prod",
        "√": "sqrt",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)

    # Decompose accented characters and strip combining marks
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))

    return text.encode("latin-1", errors="replace").decode("latin-1")


def save_pdf(md_text: str, work_space_paths: WorkspacePaths) -> str:
    Path(work_space_paths.outputs).mkdir(parents=True, exist_ok=True)

    pdf = _ReviewPDF()
    pdf.add_markdown(md_text)

    path = Path(work_space_paths.outputs) / f"review_{_safe_timestamp()}.pdf"
    pdf.output(str(path))
    return str(path)
