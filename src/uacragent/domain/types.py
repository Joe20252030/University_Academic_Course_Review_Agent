from __future__ import annotations

from enum import Enum


class ExamFormat(str, Enum):
    written = "written"
    mcq = "mcq"
    mixed = "mixed"
    unknown = "unknown"


class ExamType(str, Enum):
    """The kind of exam the student is preparing for."""
    quiz = "quiz"
    midterm = "midterm"
    final = "final"
    term_test = "term_test"
    other = "other"


class TaskType(str, Enum):
    """What the user wants the agent to produce."""
    review_summary = "review_summary"
    practice_booklet = "practice_booklet"
    mock_exam = "mock_exam"
    exam_prediction = "exam_prediction"


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
