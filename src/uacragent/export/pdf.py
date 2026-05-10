from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from fpdf import FPDF

from uacragent.export._utils import safe_timestamp
from uacragent.infra.workspace import WorkspacePaths

# Candidate font pairs (regular, bold).
# Bold may be None — FPDF2 will emulate bold from the regular file in that case.
_FONT_CANDIDATES: list[tuple[str, str | None]] = [
    # macOS — Arial (installed with Office or available in Supplemental)
    ("/Library/Fonts/Arial.ttf",
     "/Library/Fonts/Arial Bold.ttf"),
    ("/System/Library/Fonts/Supplemental/Arial.ttf",
     "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    # macOS — Arial Unicode (single weight, no bold file)
    ("/System/Library/Fonts/Supplemental/Arial Unicode MS.ttf", None),
    ("/Library/Fonts/Arial Unicode MS.ttf", None),
    # Linux — DejaVu Sans
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    # Linux — Noto Sans
    ("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
     "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"),
    # Windows — Arial
    ("C:/Windows/Fonts/arial.ttf",
     "C:/Windows/Fonts/arialbd.ttf"),
    ("C:/Windows/Fonts/arialuni.ttf", None),
]


def _find_fonts() -> tuple[str, str | None] | None:
    """Return (regular_path, bold_path_or_None) for the first available font pair.

    *bold_path* is None when only a single-weight font was found; FPDF2 will
    simulate bold using the regular file in that case.
    """
    for regular, bold in _FONT_CANDIDATES:
        if Path(regular).exists():
            bold_path = bold if (bold and Path(bold).exists()) else None
            return regular, bold_path
    return None


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

        fonts = _find_fonts()
        if fonts:
            regular, bold = fonts
            self.add_font("Unicode", "", regular)
            # Register bold variant; if no separate bold file, use the regular
            # file — FPDF2 will simulate bold from it.
            self.add_font("Unicode", "B", bold or regular)
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
        # Reset x to the left margin before multi_cell.  FPDF2 ≥ 2.7 leaves x
        # at the right margin after multi_cell returns, so any caller that does
        # not emit a ln() before calling _paragraph would inherit x ≈ 200 mm,
        # making the computed available width ≈ 0 and crashing.
        self.set_x(self.l_margin)
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

    path = Path(work_space_paths.outputs) / f"review_{safe_timestamp()}.pdf"
    pdf.output(str(path))
    return str(path)
