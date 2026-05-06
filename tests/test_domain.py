"""Tests for domain models and types."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from uacragent.domain.models import ReviewPlan, SectionSpec
from uacragent.domain.types import (
    DocumentType,
    ExamFormat,
    ExamType,
    ExportFormat,
    TaskType,
)


# ---------------------------------------------------------------------------
# SectionSpec
# ---------------------------------------------------------------------------

def test_section_spec_valid():
    s = SectionSpec(title="Sorting", key_topics=["quicksort", "mergesort"], importance=3)
    assert s.title == "Sorting"
    assert len(s.key_topics) == 2
    assert s.importance == 3


def test_section_spec_importance_bounds():
    with pytest.raises(ValidationError):
        SectionSpec(title="X", key_topics=["a"], importance=0)
    with pytest.raises(ValidationError):
        SectionSpec(title="X", key_topics=["a"], importance=6)


def test_section_spec_key_topics_min_length():
    with pytest.raises(ValidationError):
        SectionSpec(title="X", key_topics=[], importance=1)


# ---------------------------------------------------------------------------
# ReviewPlan
# ---------------------------------------------------------------------------

def test_review_plan_minimal():
    plan = ReviewPlan(
        course_title="CS101",
        exam_format="written",
        sections=[SectionSpec(title="Intro", key_topics=["basics"], importance=1)],
    )
    assert plan.course_title == "CS101"
    assert plan.exam_type == "other"
    assert plan.task_type == "review_summary"


def test_review_plan_new_info_fields_default_empty():
    plan = ReviewPlan(
        course_title="CS101",
        exam_format="written",
        sections=[SectionSpec(title="T", key_topics=["a"], importance=1)],
    )
    assert plan.course_name == ""
    assert plan.university_name == ""
    assert plan.major == ""
    assert plan.course_code == ""
    assert plan.professor_name == ""
    assert plan.semester == ""
    assert plan.exam_duration == ""
    assert plan.exam_info == ""


def test_review_plan_new_info_fields_set():
    plan = ReviewPlan(
        course_title="CS101",
        exam_format="written",
        sections=[SectionSpec(title="T", key_topics=["a"], importance=1)],
        course_name="Introduction to Computer Science",
        university_name="UofT",
        major="Computer Science",
        course_code="CSC148",
        professor_name="Dr. Smith",
        semester="Fall 2024",
        exam_duration="2 hours",
        exam_info="Closed book. Formula sheet allowed.",
    )
    assert plan.course_name == "Introduction to Computer Science"
    assert plan.university_name == "UofT"
    assert plan.course_code == "CSC148"
    assert plan.semester == "Fall 2024"
    assert plan.exam_duration == "2 hours"
    assert plan.exam_info == "Closed book. Formula sheet allowed."


def test_review_plan_sections_min_length():
    with pytest.raises(ValidationError):
        ReviewPlan(course_title="X", exam_format="written", sections=[])


# ---------------------------------------------------------------------------
# Enum coverage
# ---------------------------------------------------------------------------

def test_all_enum_values_are_strings():
    for enum_cls in (DocumentType, ExamFormat, ExamType, ExportFormat, TaskType):
        for member in enum_cls:
            assert isinstance(member.value, str)


def test_task_type_round_trip():
    for tt in TaskType:
        assert TaskType(tt.value) == tt


def test_document_type_round_trip():
    for dt in DocumentType:
        assert DocumentType(dt.value) == dt
