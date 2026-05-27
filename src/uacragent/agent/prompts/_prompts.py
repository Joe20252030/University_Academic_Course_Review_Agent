"""Centralised prompt-directory reference and language-steering helpers.

All pipeline and conversation modules that need the prompt directory or a
language-steering instruction should import from here so the path is defined
in exactly one place.

Public API
----------
PROMPTS_DIR          : Path  — absolute path to this package directory.
get_language_instruction(language) -> str
    Return the language-steering paragraph for the given locale code.
    Supported codes: "auto", "en", "zh_CN".  Falls back to English for any
    unrecognised value.
"""
from __future__ import annotations

from pathlib import Path

# The directory that contains this file is also the prompts directory.
PROMPTS_DIR: Path = Path(__file__).parent

# ---------------------------------------------------------------------------
# Language-steering instructions
# ---------------------------------------------------------------------------
# "auto" (the default) lets the LLM detect and match the user's language.
# The pipeline variants use shorter instructions; the conversation system
# prompt uses the richer ones defined here.
#
# Pipeline callers (pipeline.py, reasoning.py) inject a shorter version of
# these into planner / writer prompts; conversation.py injects them into the
# system prompt verbatim via {response_language}.

_LANGUAGE_INSTRUCTIONS: dict[str, str] = {
    # Conversational system prompt variant — richer instructions.
    "auto": (
        "## Language\n\n"
        "Detect the language of the user's most recent message and reply in "
        "that same language. If the user writes in Chinese, respond in Chinese; "
        "if in English, respond in English; and so on for any other language. "
        "Maintain that language consistently throughout the reply. "
        "Use English only for technical terms that have no established "
        "translation in the user's language."
    ),
    "en": (
        "## Language\n\n"
        "Always respond in English, regardless of the language the user writes in."
    ),
    "zh_CN": (
        "## Language\n\n"
        "You MUST respond entirely in Simplified Chinese (简体中文). "
        "All replies, explanations, section headings, and any generated "
        "document content must be written in Chinese. "
        "Do not mix in English unless quoting technical terms that have no "
        "standard Chinese translation."
    ),
}

# Pipeline / planner / writer variant — injected into generation prompts.
# These are shorter because prompt templates already set the structural context.
_PIPELINE_LANGUAGE_INSTRUCTIONS: dict[str, str] = {
    "auto": (
        "Detect the language of the student context (course name, university, etc.) "
        "and produce all output in that language. Default to English when uncertain."
    ),
    "en": "Produce all output in English.",
    "zh_CN": (
        "You MUST produce all output entirely in Simplified Chinese (简体中文). "
        "All section headings, explanations, questions, and answers must be written "
        "in Chinese. Use English only for established technical terms that lack a "
        "standard Chinese translation."
    ),
}


def get_language_instruction(language: str, *, pipeline: bool = False) -> str:
    """Return the language-steering instruction for *language*.

    Parameters
    ----------
    language:
        Locale code — one of ``"auto"``, ``"en"``, ``"zh_CN"``.  Falls back
        to the English instruction for any unrecognised value.
    pipeline:
        When ``True``, return the shorter pipeline variant (used in planner /
        writer / reasoning prompts).  When ``False`` (default), return the
        richer conversational variant (used in the chat system prompt).
    """
    table = _PIPELINE_LANGUAGE_INSTRUCTIONS if pipeline else _LANGUAGE_INSTRUCTIONS
    return table.get(language, table["en"])
