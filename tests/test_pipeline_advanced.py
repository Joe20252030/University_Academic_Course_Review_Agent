"""Advanced pipeline tests: effort config, expand_user_prefs, section cancellation,
assemble_markdown exam_prediction paths, _task_title localisation."""
from __future__ import annotations

import threading

import pytest
from langchain_core.documents import Document

from uacragent.agent.pipeline import (
    _expand_user_prefs,
    _task_title,
    assemble_markdown,
    build_outline,
    get_effort_config,
    write_sections_sequential,
)
from uacragent.domain.models import ReviewPlan, SectionSpec
from uacragent.domain.types import TaskType


# ---------------------------------------------------------------------------
# get_effort_config
# ---------------------------------------------------------------------------

def test_get_effort_config_known_levels():
    low = get_effort_config("low")
    med = get_effort_config("medium")
    high = get_effort_config("high")
    assert low.retriever_k < med.retriever_k < high.retriever_k
    assert low.outline_max_docs < med.outline_max_docs < high.outline_max_docs
    assert low.outline_chars < med.outline_chars < high.outline_chars


def test_get_effort_config_unknown_falls_back_to_medium():
    cfg = get_effort_config("ultramax")
    medium = get_effort_config("medium")
    assert cfg.retriever_k == medium.retriever_k


# ---------------------------------------------------------------------------
# _expand_user_prefs
# ---------------------------------------------------------------------------

def test_expand_user_prefs_fills_missing_optional():
    prefs = {"exam_format": "written"}
    expanded = _expand_user_prefs(prefs)
    assert expanded["university_name"] == "Not specified"
    assert expanded["major"] == "Not specified"
    assert expanded["professor_name"] == "Not specified"
    assert expanded["extra_instructions"] == "None"


def test_expand_user_prefs_preserves_existing():
    prefs = {"university_name": "UofT", "major": "CS"}
    expanded = _expand_user_prefs(prefs)
    assert expanded["university_name"] == "UofT"
    assert expanded["major"] == "CS"


def test_expand_user_prefs_does_not_mutate_input():
    prefs = {"exam_format": "mcq"}
    expanded = _expand_user_prefs(prefs)
    assert "university_name" not in prefs


def test_expand_user_prefs_empty_string_is_falsy_replaced():
    prefs = {"university_name": ""}
    expanded = _expand_user_prefs(prefs)
    assert expanded["university_name"] == "Not specified"


# ---------------------------------------------------------------------------
# _task_title localisation
# ---------------------------------------------------------------------------

def test_task_title_english():
    assert _task_title(TaskType.review_summary, "en") == "Exam Review"
    assert _task_title(TaskType.practice_booklet, "en") == "Practice Booklet"
    assert _task_title(TaskType.mock_exam, "en") == "Mock Exam"
    assert _task_title(TaskType.exam_prediction, "en") == "Exam Prediction"


def test_task_title_chinese():
    assert _task_title(TaskType.review_summary, "zh_CN") == "考试复习"
    assert _task_title(TaskType.practice_booklet, "zh_CN") == "练习册"


def test_task_title_unknown_language_falls_back_to_english():
    title = _task_title(TaskType.mock_exam, "fr_FR")
    assert title == "Mock Exam"


# ---------------------------------------------------------------------------
# build_outline sampling
# ---------------------------------------------------------------------------

def test_build_outline_includes_first_and_last_doc():
    docs = [Document(page_content=f"doc_{i}", metadata={}) for i in range(30)]
    result = build_outline(docs, max_docs=5, chars_per_doc=100)
    assert "doc_0" in result
    assert "doc_29" in result


def test_build_outline_single_doc():
    docs = [Document(page_content="only doc", metadata={})]
    result = build_outline(docs, max_docs=20, chars_per_doc=100)
    assert "only doc" in result


# ---------------------------------------------------------------------------
# assemble_markdown — exam_prediction paths
# ---------------------------------------------------------------------------

def _make_plan(**kwargs):
    defaults = dict(
        course_title="CS 101",
        exam_format="written",
        sections=[SectionSpec(title="Topic A", key_topics=["concept"], importance=3)],
    )
    defaults.update(kwargs)
    return ReviewPlan(**defaults)


def test_assemble_markdown_exam_prediction_with_paper():
    plan = _make_plan()
    md = assemble_markdown(
        plan,
        sections=["## Part A Section"],
        task_type="exam_prediction",
        paper_text="**Question 1:** Explain recursion.",
    )
    assert "Part A: Prediction Analysis" in md
    assert "Part B: Predicted Exam Paper" in md
    assert "recursion" in md


def test_assemble_markdown_exam_prediction_no_paper():
    plan = _make_plan()
    md = assemble_markdown(
        plan,
        sections=["## Analysis"],
        task_type="exam_prediction",
        paper_text="",
    )
    assert "Part B" not in md


def test_assemble_markdown_chinese_title():
    plan = _make_plan()
    md = assemble_markdown(plan, sections=[], task_type="review_summary", language="zh_CN")
    assert "考试复习" in md


def test_assemble_markdown_no_sections_no_crash():
    plan = _make_plan()
    md = assemble_markdown(plan, sections=[], task_type="review_summary")
    assert plan.course_title in md


# ---------------------------------------------------------------------------
# write_sections_sequential — cancellation
# ---------------------------------------------------------------------------

class _FakeSection:
    def __init__(self, title: str, key_topics: list):
        self.title = title
        self.key_topics = key_topics


class _FakeLLMClient:
    def stream_invoke(self, messages, cancel_event=None):
        if cancel_event and cancel_event.is_set():
            return None
        class _Resp:
            content = "Section content from LLM."
        return _Resp()


class _FakeRetriever:
    def invoke(self, query):
        return [Document(page_content="relevant chunk", metadata={})]


def _make_spec(title="T", topics=None):
    return SectionSpec(title=title, key_topics=topics or ["a"], importance=3)


def test_write_sections_sequential_normal():
    sections = [_make_spec(f"Sec {i}") for i in range(3)]
    results = write_sections_sequential(
        sections=sections,
        retriever=_FakeRetriever(),
        llm_client=_FakeLLMClient(),
        user_prefs={"task_type": "review_summary"},
        request_delay=0.0,
    )
    assert len(results) == 3
    assert all(r == "Section content from LLM." for r in results)


def test_write_sections_sequential_cancel_before_start():
    cancel = threading.Event()
    cancel.set()
    sections = [_make_spec("T")]
    results = write_sections_sequential(
        sections=sections,
        retriever=_FakeRetriever(),
        llm_client=_FakeLLMClient(),
        user_prefs={"task_type": "review_summary"},
        request_delay=0.0,
        cancel_event=cancel,
    )
    assert results == []


def test_write_sections_sequential_returns_partial_on_cancel():
    # Cancel after first section completes
    cancel = threading.Event()
    write_count = [0]

    class _CountingLLM:
        def stream_invoke(self, messages, cancel_event=None):
            write_count[0] += 1
            if write_count[0] >= 2:
                cancel_event.set()
            class _R:
                content = f"content_{write_count[0]}"
            return _R()

    sections = [_make_spec(f"S{i}") for i in range(5)]
    results = write_sections_sequential(
        sections=sections,
        retriever=_FakeRetriever(),
        llm_client=_CountingLLM(),
        user_prefs={"task_type": "review_summary"},
        request_delay=0.0,
        cancel_event=cancel,
    )
    # Should have at least the first completed section
    assert len(results) >= 1
    assert len(results) < 5


def test_write_sections_sequential_empty_sections():
    results = write_sections_sequential(
        sections=[],
        retriever=_FakeRetriever(),
        llm_client=_FakeLLMClient(),
        user_prefs={"task_type": "review_summary"},
        request_delay=0.0,
    )
    assert results == []


def test_write_sections_sequential_progress_callback():
    calls = []
    sections = [_make_spec("T")]
    write_sections_sequential(
        sections=sections,
        retriever=_FakeRetriever(),
        llm_client=_FakeLLMClient(),
        user_prefs={"task_type": "review_summary"},
        request_delay=0.0,
        progress_cb=calls.append,
    )
    assert any("Writing section" in c for c in calls)
