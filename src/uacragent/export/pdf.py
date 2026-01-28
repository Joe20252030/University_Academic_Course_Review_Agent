from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from fpdf import FPDF

from uacragent.infra.workspace import WorkspacePaths


def _safe_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


class _ReviewPDF(FPDF):
    """Thin FPDF2 subclass that converts simplified Markdown to PDF."""

    def __init__(self) -> None:
        super().__init__()
        self.add_page()
        self.set_auto_page_break(auto=True, margin=15)
        # Use built-in fonts (available everywhere, no file needed).
        self.set_font("Helvetica", size=11)

    # ------------------------------------------------------------------
    def _heading(self, text: str, level: int) -> None:
        sizes = {1: 20, 2: 16, 3: 13}
        self.set_font("Helvetica", style="B", size=sizes.get(level, 12))
        self.ln(4)
        self.multi_cell(0, 8, text)
        self.ln(2)
        self.set_font("Helvetica", size=11)

    def _bullet(self, text: str) -> None:
        self.set_x(15)
        self.cell(6, 6, "-")
        self.multi_cell(0, 6, text)

    def _numbered(self, text: str, number: str) -> None:
        self.set_x(15)
        self.cell(8, 6, f"{number}")
        self.multi_cell(0, 6, text)

    def _paragraph(self, text: str) -> None:
        self.multi_cell(0, 6, text)
        self.ln(2)

    @staticmethod
    def _sanitize(text: str) -> str:
        """Replace characters outside latin-1 with safe ASCII equivalents."""
        replacements = {
            "\u2018": "'", "\u2019": "'",   # smart quotes
            "\u201c": '"', "\u201d": '"',
            "\u2013": "-", "\u2014": "--",  # en/em dash
            "\u2022": "-",                  # bullet
            "\u2026": "...",                # ellipsis
        }
        for src, dst in replacements.items():
            text = text.replace(src, dst)
        # Drop any remaining non-latin-1 characters
        return text.encode("latin-1", errors="replace").decode("latin-1")

    # ------------------------------------------------------------------
    def add_markdown(self, md_text: str) -> None:
        md_text = self._sanitize(md_text)
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


def save_pdf(md_text: str, work_space_paths: WorkspacePaths) -> str:
    Path(work_space_paths.outputs).mkdir(parents=True, exist_ok=True)

    pdf = _ReviewPDF()
    pdf.add_markdown(md_text)

    path = Path(work_space_paths.outputs) / f"review_{_safe_timestamp()}.pdf"
    pdf.output(str(path))
    return str(path)
