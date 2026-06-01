"""Tests for domain/doc_priorities.py."""
from __future__ import annotations

import pytest

from uacragent.domain.doc_priorities import (
    DOC_WEIGHTS,
    DEFAULT_WEIGHTS,
    get_doc_weights,
    get_present_weights,
)
from uacragent.domain.types import DocumentType, TaskType


# ---------------------------------------------------------------------------
# Weight matrix coverage
# ---------------------------------------------------------------------------

def test_all_task_types_have_weights():
    for tt in TaskType:
        weights = get_doc_weights(tt)
        assert weights, f"No weights for {tt}"


def test_all_doc_types_covered_per_task():
    for tt in TaskType:
        weights = get_doc_weights(tt)
        for dt in DocumentType:
            assert dt in weights, f"{dt} missing from {tt} weights"


def test_weights_are_non_negative():
    for tt in TaskType:
        for w in get_doc_weights(tt).values():
            assert w >= 0.0


def test_past_exam_highest_for_exam_prediction():
    w = get_doc_weights(TaskType.exam_prediction)
    max_dt = max(w, key=w.get)
    assert max_dt == DocumentType.past_exam


def test_syllabus_high_for_review_summary():
    w = get_doc_weights(TaskType.review_summary)
    assert w[DocumentType.syllabus] >= 1.5


def test_assignment_high_for_practice_booklet():
    w = get_doc_weights(TaskType.practice_booklet)
    assert w[DocumentType.assignment] >= 2.0


def test_default_weights_all_equal():
    assert len(set(DEFAULT_WEIGHTS.values())) == 1


# ---------------------------------------------------------------------------
# get_present_weights
# ---------------------------------------------------------------------------

def test_get_present_weights_excludes_empty_buckets():
    classified = {
        DocumentType.syllabus: ["/a/syllabus.pdf"],
        DocumentType.lecture_note: [],  # empty — should be excluded
        DocumentType.past_exam: ["/a/exam.pdf"],
    }
    present = get_present_weights(TaskType.exam_prediction, classified)
    assert "syllabus" in present
    assert "past_exam" in present
    assert "lecture_note" not in present


def test_get_present_weights_returns_string_keys():
    classified = {DocumentType.syllabus: ["/a/syllabus.pdf"]}
    present = get_present_weights(TaskType.review_summary, classified)
    assert all(isinstance(k, str) for k in present)


def test_get_present_weights_empty_classified():
    present = get_present_weights(TaskType.mock_exam, {})
    assert present == {}


def test_get_present_weights_all_types():
    classified = {dt: [f"/f/{dt.value}.pdf"] for dt in DocumentType}
    present = get_present_weights(TaskType.review_summary, classified)
    assert len(present) == len(DocumentType)
