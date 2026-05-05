"""Tests for pure pipeline utility functions (no LLM calls)."""
from __future__ import annotations

import pytest
from langchain_core.documents import Document

from uacragent.agent.pipeline import (
    assemble_markdown,
    build_outline,
)
from uacragent.domain.models import ReviewPlan, SectionSpec
from uacragent.domain.types import TaskType


# ---------------------------------------------------------------------------
# build_outline
# ---------------------------------------------------------------------------

def _make_docs(n: int, chars: int = 100) -> list[Document]:
    return [Document(page_content="x" * chars, metadata={}) for _ in range(n)]


def test_build_outline_empty():
    assert build_outline([]) == ""


def test_build_outline_fewer_than_max():
    docs = _make_docs(5, chars=200)
    result = build_outline(docs, max_docs=20, chars_per_doc=100)
    parts = result.split("\n\n")
    assert len(parts) == 5
    # Each part is truncated to chars_per_doc
    assert all(len(p) == 100 for p in parts)


def test_build_outline_more_than_max():
    docs = _make_docs(50, chars=200)
    result = build_outline(docs, max_docs=10, chars_per_doc=50)
    parts = result.split("\n\n")
    assert len(parts) == 10


def test_build_outline_exact_max():
    docs = _make_docs(10, chars=200)
    result = build_outline(docs, max_docs=10, chars_per_doc=100)
    parts = result.split("\n\n")
    assert len(parts) == 10


# ---------------------------------------------------------------------------
# assemble_markdown
# ---------------------------------------------------------------------------

def _make_plan(**kwargs) -> ReviewPlan:
    defaults = dict(
        course_title="Intro to CS",
        exam_format="written",
        exam_type="final",
        task_type="review_summary",
        sections=[SectionSpec(title="Algorithms", key_topics=["sorting"], importance=3)],
    )
    defaults.update(kwargs)
    return ReviewPlan(**defaults)


def test_assemble_markdown_basic():
    plan = _make_plan()
    md = assemble_markdown(plan, ["## Section body"], task_type="review_summary")
    assert "# Intro to CS - Exam Review" in md
    assert "## Section body" in md


def test_assemble_markdown_course_info_in_header():
    plan = _make_plan(
        university_name="UofT",
        major="Computer Science",
        course_code="CSC148",
        professor_name="Dr. Smith",
        semester="Fall 2024",
        course_name="Introduction to Computer Science",
    )
    md = assemble_markdown(plan, [], task_type="review_summary")
    assert "UofT" in md
    assert "CSC148" in md
    assert "Dr. Smith" in md
    assert "Fall 2024" in md


def test_assemble_markdown_empty_info_omitted():
    plan = _make_plan(university_name="", major="", course_code="")
    md = assemble_markdown(plan, [], task_type="review_summary")
    # Should not contain empty bold labels
    assert "**University:**" not in md
    assert "**Major:**" not in md


def test_assemble_markdown_task_type_titles():
    plan = _make_plan()
    for task_type, expected_suffix in [
        ("review_summary", "Exam Review"),
        ("practice_booklet", "Practice Booklet"),
        ("mock_exam", "Mock Exam"),
        ("exam_prediction", "Exam Prediction"),
    ]:
        md = assemble_markdown(plan, [], task_type=task_type)
        assert expected_suffix in md


def test_assemble_markdown_invalid_task_type_defaults():
    plan = _make_plan()
    md = assemble_markdown(plan, [], task_type="nonexistent_type")
    assert "# Intro to CS - Exam Review" in md


def test_assemble_markdown_sections_joined():
    plan = _make_plan()
    sections = ["## Section A\nContent A", "## Section B\nContent B"]
    md = assemble_markdown(plan, sections, task_type="review_summary")
    assert "Content A" in md
    assert "Content B" in md
