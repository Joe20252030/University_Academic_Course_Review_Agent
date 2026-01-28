from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from docx import Document as DocxDocument
from docx.shared import Pt

from uacragent.infra.workspace import WorkspacePaths


def _safe_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def _add_markdown_to_docx(doc: DocxDocument, md_text: str) -> None:
    """Convert simplified Markdown into python-docx paragraphs.

    Handles headings (# / ## / ###), bullet lists (- / *), and plain
    paragraphs.  This is intentionally simple; a full Markdown parser
    (e.g. markdown-it) is overkill for review documents.
    """
    for line in md_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        # Headings
        if stripped.startswith("### "):
            p = doc.add_heading(stripped[4:], level=3)
        elif stripped.startswith("## "):
            p = doc.add_heading(stripped[3:], level=2)
        elif stripped.startswith("# "):
            p = doc.add_heading(stripped[2:], level=1)
        # Bullet lists
        elif re.match(r"^[-*]\s", stripped):
            p = doc.add_paragraph(stripped[2:], style="List Bullet")
        # Numbered lists
        elif re.match(r"^\d+\.\s", stripped):
            text = re.sub(r"^\d+\.\s", "", stripped)
            p = doc.add_paragraph(text, style="List Number")
        else:
            p = doc.add_paragraph(stripped)

        # Apply a readable body font size
        for run in p.runs:
            run.font.size = Pt(11)


def save_docx(md_text: str, work_space_paths: WorkspacePaths) -> str:
    Path(work_space_paths.outputs).mkdir(parents=True, exist_ok=True)

    doc = DocxDocument()
    _add_markdown_to_docx(doc, md_text)

    path = Path(work_space_paths.outputs) / f"review_{_safe_timestamp()}.docx"
    doc.save(str(path))
    return str(path)
