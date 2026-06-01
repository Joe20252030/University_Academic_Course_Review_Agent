"""Tests for DocumentLoader (file loading and splitting) — no LLM required."""
from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.documents import Document

from uacragent.domain.types import DocumentType
from uacragent.infra.loaders import (
    DocumentLoader,
    run_splitting_pipeline,
)
from uacragent.infra.settings import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        google_api_key="fake-key-for-tests",
        workspace_root=tmp_path,
    )


@pytest.fixture
def loader(settings: Settings) -> DocumentLoader:
    return DocumentLoader(settings)


# ---------------------------------------------------------------------------
# run_splitting_pipeline
# ---------------------------------------------------------------------------

def _make_doc(text: str) -> Document:
    return Document(page_content=text, metadata={"source": "test"})


def test_run_splitting_pipeline_other():
    doc = _make_doc("Hello world. " * 200)
    chunks = run_splitting_pipeline([doc], DocumentType.other)
    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.metadata.get("doc_type") == DocumentType.other.value


def test_run_splitting_pipeline_stamps_doc_type():
    for doc_type in DocumentType:
        doc = _make_doc("Some content. " * 100)
        chunks = run_splitting_pipeline([doc], doc_type)
        assert all(c.metadata.get("doc_type") == doc_type.value for c in chunks)


def test_run_splitting_pipeline_past_exam_boundary():
    exam_text = (
        "\n1. What is an algorithm?\n\nAn algorithm is a step-by-step procedure.\n"
        "\n2. Define recursion.\n\nRecursion is when a function calls itself.\n"
        "\nQ3 Explain sorting.\n\nSorting arranges elements in order.\n"
    )
    chunks = run_splitting_pipeline([_make_doc(exam_text)], DocumentType.past_exam)
    assert len(chunks) > 0


def test_run_splitting_pipeline_preserves_metadata():
    doc = Document(page_content="Content. " * 100, metadata={"source": "file.pdf", "page": 1})
    chunks = run_splitting_pipeline([doc], DocumentType.lecture_note)
    for chunk in chunks:
        assert chunk.metadata.get("source") == "file.pdf"


def test_run_splitting_pipeline_empty_docs():
    chunks = run_splitting_pipeline([], DocumentType.other)
    assert chunks == []


# ---------------------------------------------------------------------------
# DocumentLoader.load_single_file
# ---------------------------------------------------------------------------

def test_load_txt_file(loader: DocumentLoader, tmp_path: Path):
    f = tmp_path / "notes.txt"
    f.write_text("Hello, this is a test document.", encoding="utf-8")
    docs = loader.load_single_file(str(f))
    assert len(docs) >= 1
    assert "Hello" in docs[0].page_content


def test_load_md_file(loader: DocumentLoader, tmp_path: Path):
    f = tmp_path / "notes.md"
    f.write_text("# Title\n\nSome content here.", encoding="utf-8")
    docs = loader.load_single_file(str(f))
    assert len(docs) >= 1


def test_load_unsupported_extension_raises(loader: DocumentLoader, tmp_path: Path):
    from uacragent.domain.errors import IngestError
    # .csv is now supported; use a genuinely unsupported extension instead
    f = tmp_path / "data.xyz"
    f.write_text("some content")
    with pytest.raises(IngestError, match="Unsupported file type"):
        loader.load_single_file(str(f))


def test_load_missing_file_raises(loader: DocumentLoader):
    from uacragent.domain.errors import IngestError
    with pytest.raises(IngestError):
        loader.load_single_file("/nonexistent/path/file.txt")


# ---------------------------------------------------------------------------
# DocumentLoader.copy_to_workspace
# ---------------------------------------------------------------------------

def test_copy_to_workspace(loader: DocumentLoader, tmp_path: Path):
    from uacragent.infra.workspace import workspace_paths, ensure_workspace_dirs

    src = tmp_path / "notes.txt"
    src.write_text("hello")

    ws = workspace_paths(workspace_folder=tmp_path / "ws1")
    ensure_workspace_dirs(ws)

    dest = loader.copy_to_workspace(str(src), DocumentType.lecture_note, ws)
    assert Path(dest).exists()
    assert Path(dest).parent == ws.doc_folders[DocumentType.lecture_note]


def test_copy_to_workspace_reuses_identical_file(loader: DocumentLoader, tmp_path: Path):
    """Copying the same file twice returns the same destination path (no new copy)."""
    from uacragent.infra.workspace import workspace_paths, ensure_workspace_dirs

    src = tmp_path / "notes.txt"
    src.write_text("hello")

    ws = workspace_paths(workspace_folder=tmp_path / "ws2")
    ensure_workspace_dirs(ws)

    dest1 = loader.copy_to_workspace(str(src), DocumentType.other, ws)
    dest2 = loader.copy_to_workspace(str(src), DocumentType.other, ws)
    # Same content → reuse the existing workspace copy, no new file created.
    assert dest1 == dest2
    assert Path(dest1).exists()


def test_copy_to_workspace_avoids_overwrite_different_content(
    loader: DocumentLoader, tmp_path: Path
):
    """A different file with the same name still gets a unique suffixed path."""
    from uacragent.infra.workspace import workspace_paths, ensure_workspace_dirs

    src_a = tmp_path / "notes.txt"
    src_a.write_text("content A")
    src_b = tmp_path / "other_dir" / "notes.txt"
    src_b.parent.mkdir()
    src_b.write_text("content B — different from A")

    ws = workspace_paths(workspace_folder=tmp_path / "ws3")
    ensure_workspace_dirs(ws)

    dest1 = loader.copy_to_workspace(str(src_a), DocumentType.other, ws)
    dest2 = loader.copy_to_workspace(str(src_b), DocumentType.other, ws)
    # Different content → must not overwrite; second file gets a suffixed name.
    assert dest1 != dest2
    assert Path(dest1).exists()
    assert Path(dest2).exists()
    assert Path(dest1).read_text() == "content A"
    assert Path(dest2).read_text() == "content B — different from A"
