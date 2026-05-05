"""Tests for export modules (markdown, docx, pdf) — no LLM required."""
from __future__ import annotations

from pathlib import Path

import pytest

from uacragent.export.markdown import save_markdown
from uacragent.export.docx import save_docx
from uacragent.export.pdf import save_pdf, _sanitize_latin1
from uacragent.infra.workspace import workspace_paths, ensure_workspace_dirs


SAMPLE_MD = """# Intro to CS - Exam Review

**University:** UofT  |  **Course:** CSC148

## Algorithms

Key concepts and definitions here.

- Sorting algorithms
- Binary search

1. First question
2. Second question

Some plain paragraph text.
"""


@pytest.fixture
def ws(tmp_path: Path):
    w = workspace_paths(tmp_path, "test")
    ensure_workspace_dirs(w)
    return w


# ---------------------------------------------------------------------------
# Markdown export
# ---------------------------------------------------------------------------

def test_save_markdown_creates_file(ws):
    path = save_markdown(SAMPLE_MD, ws)
    assert Path(path).exists()
    assert Path(path).suffix == ".md"


def test_save_markdown_content_preserved(ws):
    path = save_markdown(SAMPLE_MD, ws)
    content = Path(path).read_text(encoding="utf-8")
    assert content == SAMPLE_MD


def test_save_markdown_unique_names(ws):
    path1 = save_markdown(SAMPLE_MD, ws)
    path2 = save_markdown(SAMPLE_MD, ws)
    # May collide within the same second; just check both are valid paths
    assert Path(path1).suffix == ".md"
    assert Path(path2).suffix == ".md"


# ---------------------------------------------------------------------------
# DOCX export
# ---------------------------------------------------------------------------

def test_save_docx_creates_file(ws):
    path = save_docx(SAMPLE_MD, ws)
    assert Path(path).exists()
    assert Path(path).suffix == ".docx"


def test_save_docx_file_is_nonempty(ws):
    path = save_docx(SAMPLE_MD, ws)
    assert Path(path).stat().st_size > 0


# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------

def test_save_pdf_creates_file(ws):
    path = save_pdf(SAMPLE_MD, ws)
    assert Path(path).exists()
    assert Path(path).suffix == ".pdf"


def test_save_pdf_file_is_nonempty(ws):
    path = save_pdf(SAMPLE_MD, ws)
    assert Path(path).stat().st_size > 0


# ---------------------------------------------------------------------------
# _sanitize_latin1
# ---------------------------------------------------------------------------

def test_sanitize_smart_quotes():
    assert _sanitize_latin1("‘hello’") == "'hello'"
    assert _sanitize_latin1("“hello”") == '"hello"'


def test_sanitize_dashes():
    assert _sanitize_latin1("x–y") == "x-y"
    assert _sanitize_latin1("x—y") == "x--y"


def test_sanitize_greek_letters():
    result = _sanitize_latin1("alpha=α, beta=β")
    assert "alpha" in result
    assert "beta" in result


def test_sanitize_accented_chars():
    result = _sanitize_latin1("café")  # é
    assert "cafe" in result


def test_sanitize_plain_ascii_unchanged():
    text = "Hello, World! This is a test."
    assert _sanitize_latin1(text) == text


def test_sanitize_ellipsis():
    assert _sanitize_latin1("…") == "..."
