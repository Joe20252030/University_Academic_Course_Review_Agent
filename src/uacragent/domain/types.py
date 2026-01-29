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


class DocumentType(str, Enum):
    """Classification of course materials for targeted processing."""
    syllabus = "syllabus"
    lecture_note = "lecture_note"
    textbook = "textbook"
    assignment = "assignment"
    past_exam = "past_exam"
    other = "other"
