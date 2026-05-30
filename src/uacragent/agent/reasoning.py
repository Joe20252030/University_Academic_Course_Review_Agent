"""Dual-level reasoning system for UACRAgent.

Two user-selectable reasoning modes control retrieval depth, multi-step
reasoning, and output quality.  The distinction is purely about token
consumption, latency, and output depth — not about paid vs. free tiers.

    Quick Review Mode
        Single-pass reasoning with a smaller context window.
        Faster, lower token usage, suitable for quick studying or a
        limited API budget.

    Deep Analysis Mode
        Multi-stage pipeline: structured topic extraction → enhanced
        retrieval → section writing → critic/refinement verification.
        Higher quality, more comprehensive, greater token usage.

Adding a new mode requires exactly one entry in ``_REASONING_CONFIGS``.

Public API
----------
get_reasoning_config(mode)  → ReasoningConfig
extract_topics(...)         → TopicList | None   (Deep only)
build_topic_context(...)    → str
apply_critic_pass(...)      → str                (Deep only)
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from uacragent.agent.prompts._prompts import PROMPTS_DIR as _PROMPTS_DIR  # noqa: E402


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReasoningConfig:
    """Parameters that govern one reasoning mode.

    All scale factors are multiplied against the active ``EffortConfig``
    values so the two independent axes (effort level + reasoning mode)
    compose cleanly without hard-coding absolute numbers.

    Attributes
    ----------
    retriever_k_scale      : Multiplier applied to ``effort.retriever_k``.
    outline_chars_scale    : Multiplier applied to ``effort.outline_chars``.
    outline_max_docs_scale : Multiplier applied to ``effort.outline_max_docs``.
    enable_topic_extraction: Run a structured topic-extraction LLM call
                             before plan generation and inject results into
                             the planner prompt for better section prioritisation.
    enable_critic_pass     : After writing each section run a refinement LLM
                             call to improve accuracy, depth, and structure.
    max_sections           : Hard cap on the number of plan sections.
                             ``None`` means no cap (use whatever the planner
                             produces).  Quick mode caps at 6 to keep output
                             concise and token-efficient.
    ui_description         : Short phrase displayed in the UI chip tooltip /
                             menu item so users understand the trade-off.
    """

    retriever_k_scale: float
    outline_chars_scale: float
    outline_max_docs_scale: float
    enable_topic_extraction: bool
    enable_critic_pass: bool
    max_sections: int | None
    ui_description: str


_REASONING_CONFIGS: dict[str, ReasoningConfig] = {
    # ── Quick Review Mode ─────────────────────────────────────────────────────
    # Prioritises speed and token efficiency.  Suitable for quick study sessions
    # or users with limited API budget.  Uses a single-pass reasoning approach
    # with a reduced retrieval window and a capped section count.
    "quick": ReasoningConfig(
        retriever_k_scale=0.75,
        outline_chars_scale=0.6,
        outline_max_docs_scale=0.5,
        enable_topic_extraction=False,
        enable_critic_pass=False,
        max_sections=6,
        ui_description="Faster generation with lower token usage.",
    ),
    # ── Deep Analysis Mode ────────────────────────────────────────────────────
    # Prioritises output quality and reasoning depth.  Performs structured topic
    # extraction before planning so the LLM can prioritise exam-relevant content,
    # uses a wider retrieval window, and refines each section with a critic pass.
    "deep": ReasoningConfig(
        retriever_k_scale=1.5,
        outline_chars_scale=1.5,
        outline_max_docs_scale=1.5,
        enable_topic_extraction=True,
        enable_critic_pass=True,
        max_sections=None,
        ui_description="More comprehensive reasoning with higher token usage.",
    ),
}

_DEFAULT_REASONING_MODE = "quick"


def get_reasoning_config(mode: str) -> ReasoningConfig:
    """Return the :class:`ReasoningConfig` for *mode*, defaulting to quick.

    Never raises — an unknown mode silently falls back to Quick so the
    application stays functional even if a session file contains a stale
    reasoning-mode string.
    """
    return _REASONING_CONFIGS.get(mode, _REASONING_CONFIGS[_DEFAULT_REASONING_MODE])


# ---------------------------------------------------------------------------
# Structured output models
# ---------------------------------------------------------------------------

class TopicScore(BaseModel):
    """Exam-relevance assessment for a single course topic."""

    topic: str = Field(
        ...,
        description="Clear, concise name of the topic or concept.",
    )
    importance_score: int = Field(
        ..., ge=1, le=5,
        description=(
            "Estimated exam weight: "
            "5=core/almost certainly tested, 4=likely, 3=possible, "
            "2=peripheral, 1=background only."
        ),
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0,
        description="Confidence in this assessment (0.0 = uncertain, 1.0 = certain).",
    )


class TopicList(BaseModel):
    """Ordered collection of topic assessments from deep analysis."""

    topics: list[TopicScore] = Field(
        ..., min_length=1,
        description="List of extracted topic assessments.",
    )


# ---------------------------------------------------------------------------
# Prompt loader
# ---------------------------------------------------------------------------

def _load_reasoning_prompt(name: str) -> str:
    """Read a reasoning prompt template by name from the prompts directory."""
    from uacragent.domain.errors import LLMError

    path = _PROMPTS_DIR / name
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise LLMError(
            f"Reasoning prompt '{name}' not found in {_PROMPTS_DIR}. "
            "This is an installation error — please reinstall the package."
        ) from None
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"Could not read reasoning prompt '{name}': {exc}") from exc


# ---------------------------------------------------------------------------
# Deep-analysis: topic extraction
# ---------------------------------------------------------------------------

def extract_topics(
    outline: str,
    user_prefs: dict,
    llm_client: Any,
    cancel_event: "threading.Event | None" = None,
) -> TopicList | None:
    """Extract a ranked list of exam-relevant topics from the document outline.

    Uses a structured LLM call (``generate_structured``) so the output is a
    validated :class:`TopicList` Pydantic object rather than raw text.

    Returns *None* on any failure so callers can degrade gracefully to the
    standard single-pass planning path without interrupting the pipeline.

    Parameters
    ----------
    outline:
        The condensed document outline text produced by ``build_outline()``.
    user_prefs:
        The user preferences dict (provides course name, exam type, format).
    llm_client:
        An :class:`~uacragent.infra.llm.LLMClient` instance.
    """
    try:
        template = _load_reasoning_prompt("topic_extraction.md")
        prompt = ChatPromptTemplate.from_template(template)
        messages = prompt.format_messages(
            outline=outline,
            course_name=user_prefs.get("course_name") or "the course",
            exam_type=user_prefs.get("exam_type") or "other",
            exam_format=user_prefs.get("exam_format") or "unknown",
        )
        result: TopicList = llm_client.generate_structured_cancellable(
            TopicList, messages, cancel_event
        )
        logger.info(
            "Topic extraction complete: %d topics extracted.", len(result.topics)
        )
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Topic extraction failed — continuing without it: %s", exc
        )
        return None


def build_topic_context(topic_list: TopicList | None) -> str:
    """Render a :class:`TopicList` into a compact markdown block.

    The block is appended to the document outline before it is passed to the
    planner so the planner can weight sections toward high-importance topics.

    Returns an empty string when *topic_list* is ``None`` so callers can
    safely concatenate the result without branching.
    """
    if topic_list is None:
        return ""

    lines = [
        "",
        "## Deep Analysis — Extracted Topic Priorities",
        "",
        "The following topics were identified as exam-relevant, ranked by importance:",
        "",
    ]
    for ts in sorted(topic_list.topics, key=lambda t: t.importance_score, reverse=True):
        stars = "★" * ts.importance_score + "☆" * (5 - ts.importance_score)
        conf_pct = f"{ts.confidence:.0%}"
        lines.append(f"- **{ts.topic}**  {stars}  _(confidence {conf_pct})_")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Deep-analysis: critic / refinement pass
# ---------------------------------------------------------------------------

def apply_critic_pass(
    section_text: str,
    section_title: str,
    key_topics: list[str],
    llm_client: Any,
    cancel_event: "threading.Event | None" = None,
) -> str:
    """Run a refinement LLM call to improve a written section.

    The critic checks for gaps in topic coverage, improves academic precision,
    and ensures the section structure is clean.  Falls back to the original
    *section_text* if the critic call fails so the pipeline is always resilient.

    Parameters
    ----------
    section_text:
        The raw section content produced by the writer.
    section_title:
        The section title (used in the critic prompt for context).
    key_topics:
        List of key topics the section should cover.
    llm_client:
        An :class:`~uacragent.infra.llm.LLMClient` instance.
    """
    try:
        template = _load_reasoning_prompt("section_critic.md")
        prompt = ChatPromptTemplate.from_template(template)
        topics_str = ", ".join(key_topics)
        resp = llm_client.stream_invoke(
            prompt.format_messages(
                section_title=section_title,
                key_topics=topics_str,
                section_text=section_text,
            ),
            cancel_event=cancel_event,
        )
        if resp is None:
            return section_text  # Cancelled — keep the original section
        refined = getattr(resp, "content", str(resp))
        return refined.strip() or section_text
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Critic pass failed for section '%s' — keeping original: %s",
            section_title, exc,
        )
        return section_text
