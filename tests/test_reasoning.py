"""Tests for agent/reasoning.py — ReasoningConfig, topic context, critic."""
from __future__ import annotations

import pytest

from uacragent.agent.reasoning import (
    ReasoningConfig,
    TopicScore,
    TopicList,
    build_topic_context,
    get_reasoning_config,
)
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# get_reasoning_config
# ---------------------------------------------------------------------------

def test_quick_config_returned():
    cfg = get_reasoning_config("quick")
    assert cfg.enable_topic_extraction is False
    assert cfg.enable_critic_pass is False
    assert cfg.max_sections == 6
    assert cfg.retriever_k_scale < 1.0


def test_deep_config_returned():
    cfg = get_reasoning_config("deep")
    assert cfg.enable_topic_extraction is True
    assert cfg.enable_critic_pass is True
    assert cfg.max_sections is None
    assert cfg.retriever_k_scale > 1.0


def test_unknown_mode_falls_back_to_quick():
    cfg = get_reasoning_config("nonexistent_mode")
    quick = get_reasoning_config("quick")
    assert cfg is quick


def test_all_scale_factors_are_positive():
    for mode in ("quick", "deep"):
        cfg = get_reasoning_config(mode)
        assert cfg.retriever_k_scale > 0
        assert cfg.outline_chars_scale > 0
        assert cfg.outline_max_docs_scale > 0


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

def test_topic_score_valid():
    ts = TopicScore(topic="Sorting", importance_score=4, confidence=0.9)
    assert ts.topic == "Sorting"
    assert ts.importance_score == 4


def test_topic_score_importance_bounds():
    with pytest.raises(ValidationError):
        TopicScore(topic="X", importance_score=0, confidence=0.5)
    with pytest.raises(ValidationError):
        TopicScore(topic="X", importance_score=6, confidence=0.5)


def test_topic_score_confidence_bounds():
    with pytest.raises(ValidationError):
        TopicScore(topic="X", importance_score=3, confidence=-0.1)
    with pytest.raises(ValidationError):
        TopicScore(topic="X", importance_score=3, confidence=1.1)


def test_topic_list_requires_at_least_one():
    with pytest.raises(ValidationError):
        TopicList(topics=[])


def test_topic_list_valid():
    tl = TopicList(
        topics=[TopicScore(topic="A", importance_score=5, confidence=1.0)]
    )
    assert len(tl.topics) == 1


# ---------------------------------------------------------------------------
# build_topic_context
# ---------------------------------------------------------------------------

def test_build_topic_context_none_returns_empty():
    assert build_topic_context(None) == ""


def test_build_topic_context_contains_header():
    tl = TopicList(
        topics=[TopicScore(topic="Recursion", importance_score=5, confidence=0.95)]
    )
    ctx = build_topic_context(tl)
    assert "Deep Analysis" in ctx
    assert "Recursion" in ctx


def test_build_topic_context_sorted_descending():
    tl = TopicList(
        topics=[
            TopicScore(topic="Low", importance_score=1, confidence=0.5),
            TopicScore(topic="High", importance_score=5, confidence=0.9),
        ]
    )
    ctx = build_topic_context(tl)
    assert ctx.index("High") < ctx.index("Low")


def test_build_topic_context_stars_count():
    tl = TopicList(
        topics=[TopicScore(topic="T", importance_score=3, confidence=0.7)]
    )
    ctx = build_topic_context(tl)
    # importance_score=3 → 3 filled stars + 2 empty stars
    assert "★★★☆☆" in ctx


def test_build_topic_context_confidence_percentage():
    tl = TopicList(
        topics=[TopicScore(topic="T", importance_score=2, confidence=0.75)]
    )
    ctx = build_topic_context(tl)
    assert "75%" in ctx
