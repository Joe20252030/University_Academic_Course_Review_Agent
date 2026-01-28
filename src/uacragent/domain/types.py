from __future__ import annotations

from enum import Enum


class ExamFormat(str, Enum):
    written = "written"
    mcq = "mcq"
    mixed = "mixed"
    unknown = "unknown"


class ExportFormat(str, Enum):
    markdown = "markdown"
    docx = "docx"
    pdf = "pdf"
