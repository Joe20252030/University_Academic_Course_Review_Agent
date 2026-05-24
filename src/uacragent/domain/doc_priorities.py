"""Document priority weights — per-task-type retrieval importance matrix.

When the RAG retriever fetches *k* chunks from the vector store it normally
distributes them evenly across all doc types.  This module provides a weight
matrix that lets the pipeline bias retrieval toward the most relevant sources
for a given task.

Usage::

    from uacragent.domain.doc_priorities import get_doc_weights
    from uacragent.domain.types import TaskType

    weights = get_doc_weights(TaskType.exam_prediction)
    # {DocumentType.past_exam: 3.0, DocumentType.syllabus: 2.0, ...}

Weight semantics
----------------
Weights are *relative* — only their ratios matter.  A weight of ``3.0``
means "fetch three times as many chunks from this source compared to a
source with weight ``1.0``".  Weights of ``0.0`` exclude a doc type
entirely; anything below ``0.25`` is effectively negligible.

Weight matrix rationale
-----------------------
review_summary
    Syllabus and lecture notes dominate: they define what was taught and
    what the exam covers.  Textbooks provide supplementary depth.

practice_booklet
    Assignments and past exams are the primary source of practice
    questions.  Lecture notes provide topic scaffolding.

mock_exam
    Past exams are the strongest signal for exam format and difficulty.
    Assignments contribute additional question patterns.  Syllabus sets
    the topic scope.

exam_prediction
    Past exams carry the highest signal for what is likely to appear again.
    Syllabus scope constraints are equally important to avoid out-of-scope
    predictions.  Assignments hint at assessed skills.  Lecture notes and
    textbooks provide topic depth for the analytical sections.
"""
from __future__ import annotations

from uacragent.domain.types import DocumentType, TaskType


# ---------------------------------------------------------------------------
# Weight matrix
# ---------------------------------------------------------------------------

#: Maps (TaskType → DocumentType → relative weight).
#: Add or tune entries here; no other file needs to change.
DOC_WEIGHTS: dict[TaskType, dict[DocumentType, float]] = {
    TaskType.review_summary: {
        DocumentType.syllabus:      2.0,
        DocumentType.lecture_note:  1.5,
        DocumentType.textbook:      1.5,
        DocumentType.assignment:    1.0,
        DocumentType.past_exam:     1.0,
        DocumentType.other:         0.5,
    },
    TaskType.practice_booklet: {
        DocumentType.syllabus:      1.0,
        DocumentType.lecture_note:  1.5,
        DocumentType.textbook:      1.0,
        DocumentType.assignment:    2.0,
        DocumentType.past_exam:     2.0,
        DocumentType.other:         0.5,
    },
    TaskType.mock_exam: {
        DocumentType.syllabus:      1.5,
        DocumentType.lecture_note:  1.0,
        DocumentType.textbook:      1.0,
        DocumentType.assignment:    2.0,
        DocumentType.past_exam:     2.5,
        DocumentType.other:         0.5,
    },
    TaskType.exam_prediction: {
        DocumentType.syllabus:      2.0,
        DocumentType.lecture_note:  1.0,
        DocumentType.textbook:      1.0,
        DocumentType.assignment:    1.5,
        DocumentType.past_exam:     3.0,
        DocumentType.other:         0.5,
    },
}

#: Fallback used when a task type has no entry in ``DOC_WEIGHTS``.
DEFAULT_WEIGHTS: dict[DocumentType, float] = {
    DocumentType.syllabus:      1.0,
    DocumentType.lecture_note:  1.0,
    DocumentType.textbook:      1.0,
    DocumentType.assignment:    1.0,
    DocumentType.past_exam:     1.0,
    DocumentType.other:         1.0,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_doc_weights(task_type: TaskType) -> dict[DocumentType, float]:
    """Return the weight dict for *task_type*, falling back to equal weights."""
    return DOC_WEIGHTS.get(task_type, DEFAULT_WEIGHTS)


def get_present_weights(
    task_type: TaskType,
    classified_files: "dict[DocumentType, list[str]]",
) -> dict[str, float]:
    """Return a ``{doc_type_value: weight}`` dict restricted to doc types
    that actually have files in *classified_files*.

    Doc types with an empty file list are excluded.  The returned dict uses
    ``DocumentType.value`` strings (e.g. ``"past_exam"``) as keys so it can
    be passed directly to the Chroma ``where`` filter.
    """
    weights = get_doc_weights(task_type)
    return {
        dt.value: weights.get(dt, 1.0)
        for dt, paths in classified_files.items()
        if paths
    }
