"""Tests for vectorstore chunk deduplication logic — no LLM/Chroma required."""
from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
from langchain_core.documents import Document

from uacragent.infra.vectorstore import _chunk_id


# ---------------------------------------------------------------------------
# _chunk_id
# ---------------------------------------------------------------------------

class TestChunkId:
    def test_same_source_same_content_same_id(self):
        doc = Document(page_content="hello world", metadata={"source": "/a/b.txt"})
        assert _chunk_id(doc) == _chunk_id(doc)

    def test_different_source_same_content_different_id(self):
        doc_a = Document(page_content="hello", metadata={"source": "/path/a.pdf"})
        doc_b = Document(page_content="hello", metadata={"source": "/path/b.pdf"})
        assert _chunk_id(doc_a) != _chunk_id(doc_b)

    def test_same_source_different_content_different_id(self):
        doc_a = Document(page_content="hello", metadata={"source": "/path/f.pdf"})
        doc_b = Document(page_content="world", metadata={"source": "/path/f.pdf"})
        assert _chunk_id(doc_a) != _chunk_id(doc_b)

    def test_returns_hex_sha256(self):
        doc = Document(page_content="test", metadata={"source": "/x"})
        cid = _chunk_id(doc)
        assert len(cid) == 64
        assert all(c in "0123456789abcdef" for c in cid)

    def test_missing_source_uses_empty_string(self):
        doc = Document(page_content="content", metadata={})
        cid = _chunk_id(doc)
        expected = hashlib.sha256(("\x00content").encode("utf-8")).hexdigest()
        assert cid == expected

    def test_repeated_content_same_source_same_id(self):
        """Repeated page headers from the same file produce identical IDs."""
        doc1 = Document(page_content="Header", metadata={"source": "/f.pdf"})
        doc2 = Document(page_content="Header", metadata={"source": "/f.pdf"})
        assert _chunk_id(doc1) == _chunk_id(doc2)

    def test_null_byte_separator_prevents_concatenation_collision(self):
        """'a' + '\x00' + 'bc' must differ from 'a\x00b' + '\x00' + 'c'."""
        doc_a = Document(page_content="bc", metadata={"source": "a"})
        doc_b = Document(page_content="c",  metadata={"source": "a\x00b"})
        assert _chunk_id(doc_a) != _chunk_id(doc_b)


# ---------------------------------------------------------------------------
# get_or_create_vectorstore — deduplication logic
# ---------------------------------------------------------------------------

class TestGetOrCreateVectorstoreDedup:
    """Validate the _seen-set + existing_ids deduplication without Chroma."""

    def _make_doc(self, source: str, content: str) -> Document:
        return Document(page_content=content, metadata={"source": source})

    def _mock_db(self, existing_ids: list[str]):
        """Return a mock Chroma db whose .get() reports the given existing IDs."""
        db = MagicMock()
        # db.get(ids=batch) → {"ids": [ids that exist in this batch]}
        def _get(ids):
            matched = [i for i in ids if i in existing_ids]
            return {"ids": matched}
        db.get.side_effect = _get
        db.add_documents = MagicMock()
        return db

    @patch("uacragent.infra.vectorstore._build_embeddings")
    @patch("uacragent.infra.vectorstore.Chroma")
    @patch("uacragent.infra.vectorstore._files_were_removed", return_value=False)
    @patch("uacragent.infra.vectorstore._save_manifest")
    def test_new_chunks_are_added(
        self, mock_save, mock_removed, mock_chroma_cls, mock_embeddings, tmp_path
    ):
        from uacragent.infra.vectorstore import get_or_create_vectorstore
        from uacragent.infra.workspace import workspace_paths, ensure_workspace_dirs
        from uacragent.infra.settings import Settings

        ws = workspace_paths(workspace_folder=tmp_path / "ws")
        ensure_workspace_dirs(ws)
        settings = Settings(google_api_key="fake")

        doc = self._make_doc("/f.pdf", "unique content abc")
        db = self._mock_db(existing_ids=[])          # nothing pre-existing
        mock_chroma_cls.return_value = db

        get_or_create_vectorstore([doc], settings, ws, classified_files={})

        # One new chunk should have been added
        db.add_documents.assert_called_once()
        _, kwargs = db.add_documents.call_args
        assert len(kwargs["ids"]) == 1

    @patch("uacragent.infra.vectorstore._build_embeddings")
    @patch("uacragent.infra.vectorstore.Chroma")
    @patch("uacragent.infra.vectorstore._files_were_removed", return_value=False)
    @patch("uacragent.infra.vectorstore._save_manifest")
    def test_existing_chunks_not_re_added(
        self, mock_save, mock_removed, mock_chroma_cls, mock_embeddings, tmp_path
    ):
        from uacragent.infra.vectorstore import get_or_create_vectorstore
        from uacragent.infra.workspace import workspace_paths, ensure_workspace_dirs
        from uacragent.infra.settings import Settings

        ws = workspace_paths(workspace_folder=tmp_path / "ws")
        ensure_workspace_dirs(ws)
        settings = Settings(google_api_key="fake")

        doc = self._make_doc("/f.pdf", "already indexed content")
        cid = _chunk_id(doc)
        db = self._mock_db(existing_ids=[cid])       # already in DB

        mock_chroma_cls.return_value = db

        get_or_create_vectorstore([doc], settings, ws, classified_files={})

        # Nothing new to add
        db.add_documents.assert_not_called()

    @patch("uacragent.infra.vectorstore._build_embeddings")
    @patch("uacragent.infra.vectorstore.Chroma")
    @patch("uacragent.infra.vectorstore._files_were_removed", return_value=False)
    @patch("uacragent.infra.vectorstore._save_manifest")
    def test_within_batch_duplicates_deduplicated(
        self, mock_save, mock_removed, mock_chroma_cls, mock_embeddings, tmp_path
    ):
        """Two chunks with identical source+content must not both be sent to Chroma."""
        from uacragent.infra.vectorstore import get_or_create_vectorstore
        from uacragent.infra.workspace import workspace_paths, ensure_workspace_dirs
        from uacragent.infra.settings import Settings

        ws = workspace_paths(workspace_folder=tmp_path / "ws")
        ensure_workspace_dirs(ws)
        settings = Settings(google_api_key="fake")

        # Two documents with identical source+content → same chunk ID
        doc_a = self._make_doc("/f.pdf", "repeated header")
        doc_b = self._make_doc("/f.pdf", "repeated header")
        assert _chunk_id(doc_a) == _chunk_id(doc_b)

        db = self._mock_db(existing_ids=[])
        mock_chroma_cls.return_value = db

        get_or_create_vectorstore([doc_a, doc_b], settings, ws, classified_files={})

        # Only one of the two identical chunks should be added
        db.add_documents.assert_called_once()
        _, kwargs = db.add_documents.call_args
        assert len(kwargs["ids"]) == 1
        assert len(set(kwargs["ids"])) == 1      # no duplicates in the call

    @patch("uacragent.infra.vectorstore._build_embeddings")
    @patch("uacragent.infra.vectorstore.Chroma")
    @patch("uacragent.infra.vectorstore._files_were_removed", return_value=False)
    @patch("uacragent.infra.vectorstore._save_manifest")
    def test_empty_chunks_no_add_call(
        self, mock_save, mock_removed, mock_chroma_cls, mock_embeddings, tmp_path
    ):
        from uacragent.infra.vectorstore import get_or_create_vectorstore
        from uacragent.infra.workspace import workspace_paths, ensure_workspace_dirs
        from uacragent.infra.settings import Settings

        ws = workspace_paths(workspace_folder=tmp_path / "ws")
        ensure_workspace_dirs(ws)
        settings = Settings(google_api_key="fake")

        db = self._mock_db(existing_ids=[])
        mock_chroma_cls.return_value = db

        get_or_create_vectorstore([], settings, ws, classified_files={})

        db.add_documents.assert_not_called()


# ---------------------------------------------------------------------------
# _files_were_removed
# ---------------------------------------------------------------------------

class TestFilesWereRemoved:
    def _write_manifest(self, path: Path, file_list: list[dict]) -> None:
        """Write a manifest in the correct format: {"files": [{"doc_type": ..., "path": ...}]}."""
        import json
        path.write_text(json.dumps({"files": file_list}), encoding="utf-8")

    def test_no_manifest_returns_false(self, tmp_path):
        from uacragent.infra.vectorstore import _files_were_removed
        from uacragent.infra.workspace import workspace_paths, ensure_workspace_dirs
        from uacragent.domain.types import DocumentType

        ws = workspace_paths(workspace_folder=tmp_path / "ws")
        ensure_workspace_dirs(ws)
        # No manifest file written → treated as first run, no removals
        result = _files_were_removed(ws, {DocumentType.other: ["/a/b.pdf"]})
        assert result is False

    def test_same_files_returns_false(self, tmp_path):
        from uacragent.infra.vectorstore import _files_were_removed, _manifest_path
        from uacragent.infra.workspace import workspace_paths, ensure_workspace_dirs
        from uacragent.domain.types import DocumentType

        ws = workspace_paths(workspace_folder=tmp_path / "ws")
        ensure_workspace_dirs(ws)
        self._write_manifest(
            _manifest_path(ws),
            [{"doc_type": "lecture_note", "path": "/a/lec.pdf"}],
        )
        result = _files_were_removed(ws, {DocumentType.lecture_note: ["/a/lec.pdf"]})
        assert result is False

    def test_removed_file_returns_true(self, tmp_path):
        from uacragent.infra.vectorstore import _files_were_removed, _manifest_path
        from uacragent.infra.workspace import workspace_paths, ensure_workspace_dirs
        from uacragent.domain.types import DocumentType

        ws = workspace_paths(workspace_folder=tmp_path / "ws")
        ensure_workspace_dirs(ws)
        self._write_manifest(
            _manifest_path(ws),
            [
                {"doc_type": "lecture_note", "path": "/a/lec.pdf"},
                {"doc_type": "lecture_note", "path": "/a/old.pdf"},
            ],
        )
        # old.pdf removed from the current set
        result = _files_were_removed(ws, {DocumentType.lecture_note: ["/a/lec.pdf"]})
        assert result is True

    def test_added_file_does_not_trigger_removal(self, tmp_path):
        from uacragent.infra.vectorstore import _files_were_removed, _manifest_path
        from uacragent.infra.workspace import workspace_paths, ensure_workspace_dirs
        from uacragent.domain.types import DocumentType

        ws = workspace_paths(workspace_folder=tmp_path / "ws")
        ensure_workspace_dirs(ws)
        self._write_manifest(
            _manifest_path(ws),
            [{"doc_type": "lecture_note", "path": "/a/lec.pdf"}],
        )
        # New file added but old one still present → no removal
        result = _files_were_removed(
            ws, {DocumentType.lecture_note: ["/a/lec.pdf", "/a/new.pdf"]}
        )
        assert result is False
