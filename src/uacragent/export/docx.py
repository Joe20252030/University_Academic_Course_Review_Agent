from __future__ import annotations

import re
from pathlib import Path

from docx import Document as DocxDocument
from docx.shared import Pt

from uacragent.export._utils import safe_timestamp
from uacragent.infra.workspace import WorkspacePaths


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

        is_heading = False

        # Headings — let the built-in heading style control the font size
        if stripped.startswith("### "):
            p = doc.add_heading(stripped[4:], level=3)
            is_heading = True
        elif stripped.startswith("## "):
            p = doc.add_heading(stripped[3:], level=2)
            is_heading = True
        elif stripped.startswith("# "):
            p = doc.add_heading(stripped[2:], level=1)
            is_heading = True
        # Bullet lists
        elif re.match(r"^[-*]\s", stripped):
            p = doc.add_paragraph(stripped[2:], style="List Bullet")
        # Numbered lists
        elif re.match(r"^\d+\.\s", stripped):
            text = re.sub(r"^\d+\.\s", "", stripped)
            p = doc.add_paragraph(text, style="List Number")
        else:
            p = doc.add_paragraph(stripped)

        # Only override font size for body paragraphs.
        # Headings inherit their size from the paragraph style (H1 ≈ 16pt,
        # H2 ≈ 14pt, H3 ≈ 12pt) — forcing Pt(11) would flatten them all.
        if not is_heading:
            for run in p.runs:
                run.font.size = Pt(11)


def save_docx(md_text: str, workspace_paths: WorkspacePaths) -> str:
    Path(workspace_paths.outputs).mkdir(parents=True, exist_ok=True)

    doc = DocxDocument()
    _add_markdown_to_docx(doc, md_text)

    path = Path(workspace_paths.outputs) / f"review_{safe_timestamp()}.docx"
    doc.save(str(path))
    return str(path)
