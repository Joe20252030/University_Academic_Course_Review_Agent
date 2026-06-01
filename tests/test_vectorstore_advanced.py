"""Advanced vectorstore tests: manifest, chroma_is_current, _safe_rmtree,
_is_network_error, _embedding_fingerprint, reset_manifest, WeightedDocTypeRetriever."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from uacragent.domain.types import DocumentType, TaskType
from uacragent.infra import vectorstore as vs_mod
from uacragent.infra.vectorstore import (
    _chunk_id,
    _embedding_fingerprint,
    _is_network_error,
    _load_manifest,
    _manifest_path,
    _safe_rmtree,
    _save_manifest,
    chroma_is_current,
    reset_manifest,
    WeightedDocTypeRetriever,
    build_weighted_retriever,
)
from uacragent.infra.workspace import ensure_workspace_dirs, workspace_paths
from langchain_core.documents import Document


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ws(tmp_path, name="ws"):
    ws = workspace_paths(workspace_folder=tmp_path / name)
    ensure_workspace_dirs(ws)
    return ws


def _fake_settings(provider="gemini", model="models/text-embedding-004",
                   local_model="all-MiniLM-L6-v2"):
    s = MagicMock()
    s.embedding_provider = provider
    s.embedding_model = model
    s.local_embedding_model = local_model
    return s


# ---------------------------------------------------------------------------
# _safe_rmtree
# ---------------------------------------------------------------------------

class TestSafeRmtree:
    def test_deletes_existing_dir(self, tmp_path):
        target = tmp_path / "child"
        target.mkdir()
        (target / "file.txt").write_text("data")
        _safe_rmtree(target, tmp_path)
        assert not target.exists()

    def test_refuses_path_outside_parent(self, tmp_path):
        other = tmp_path / "other"
        other.mkdir()
        # Try to delete a sibling that resolves outside the given parent
        sibling = tmp_path.parent / "sibling"
        sibling.mkdir(exist_ok=True)
        try:
            _safe_rmtree(sibling, tmp_path)
            # Should NOT delete the sibling
            assert sibling.exists()
        finally:
            sibling.rmdir()

    def test_refuses_symlink(self, tmp_path):
        target = tmp_path / "real"
        target.mkdir()
        link = tmp_path / "link"
        link.symlink_to(target)
        _safe_rmtree(link, tmp_path)
        assert link.exists()  # symlink must not be removed
        assert target.exists()

    def test_no_op_for_nonexistent_path(self, tmp_path):
        _safe_rmtree(tmp_path / "ghost", tmp_path)  # must not raise


# ---------------------------------------------------------------------------
# _is_network_error
# ---------------------------------------------------------------------------

class TestIsNetworkError:
    def test_os_error_is_network(self):
        assert _is_network_error(OSError("connection refused"))

    def test_timeout_error_is_network(self):
        assert _is_network_error(TimeoutError("timed out"))

    def test_connection_error_by_name(self):
        exc = type("ConnectionError", (Exception,), {})("failed")
        assert _is_network_error(exc)

    def test_generic_value_error_is_not_network(self):
        assert not _is_network_error(ValueError("bad input"))

    def test_message_with_network_keyword(self):
        exc = Exception("failed to establish a new connection")
        assert _is_network_error(exc)

    def test_message_with_socket_keyword(self):
        exc = Exception("socket hangup")
        assert _is_network_error(exc)

    def test_unrelated_exception_is_not_network(self):
        assert not _is_network_error(RuntimeError("something else"))


# ---------------------------------------------------------------------------
# _embedding_fingerprint
# ---------------------------------------------------------------------------

class TestEmbeddingFingerprint:
    def test_gemini_fingerprint(self):
        s = _fake_settings(provider="gemini", model="models/text-embedding-004")
        fp = _embedding_fingerprint(s)
        assert fp.startswith("gemini::")
        assert "text-embedding-004" in fp

    def test_openai_fingerprint(self):
        s = _fake_settings(provider="openai", model="text-embedding-3-small")
        fp = _embedding_fingerprint(s)
        assert fp.startswith("openai::")

    def test_local_fingerprint_source_mode(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        s = _fake_settings(provider="local", local_model="all-MiniLM-L6-v2")
        fp = _embedding_fingerprint(s)
        assert fp.startswith("local::")
        assert "all-MiniLM-L6-v2" in fp

    def test_local_fingerprint_frozen_mode(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        s = _fake_settings(provider="local", local_model="all-MiniLM-L6-v2")
        fp = _embedding_fingerprint(s)
        assert fp.startswith("local_onnx::")

    def test_different_models_produce_different_fingerprints(self):
        s1 = _fake_settings(provider="gemini", model="v1")
        s2 = _fake_settings(provider="gemini", model="v2")
        assert _embedding_fingerprint(s1) != _embedding_fingerprint(s2)


# ---------------------------------------------------------------------------
# _save_manifest / _load_manifest
# ---------------------------------------------------------------------------

class TestManifest:
    def test_save_and_load_round_trip(self, tmp_path):
        ws = _ws(tmp_path)
        classified = {DocumentType.lecture_note: ["/a/lec.pdf"]}
        settings = _fake_settings()
        _save_manifest(ws, classified, settings)
        data = _load_manifest(ws)
        assert data
        files = data["files"]
        assert {"doc_type": "lecture_note", "path": "/a/lec.pdf"} in files

    def test_load_nonexistent_returns_empty(self, tmp_path):
        ws = _ws(tmp_path)
        assert _load_manifest(ws) == {}

    def test_load_corrupt_json_returns_empty(self, tmp_path):
        ws = _ws(tmp_path)
        _manifest_path(ws).write_text("{not valid json", encoding="utf-8")
        result = _load_manifest(ws)
        assert result == {}

    def test_embedding_config_stored(self, tmp_path):
        ws = _ws(tmp_path)
        settings = _fake_settings(provider="openai", model="text-embedding-3-small")
        _save_manifest(ws, {}, settings)
        data = _load_manifest(ws)
        assert "openai" in data["embedding_config"]

    def test_atomic_write_no_tmp_left(self, tmp_path):
        ws = _ws(tmp_path)
        _save_manifest(ws, {DocumentType.other: ["/f.pdf"]})
        tmp_file = _manifest_path(ws).with_suffix(".tmp")
        assert not tmp_file.exists()


# ---------------------------------------------------------------------------
# reset_manifest
# ---------------------------------------------------------------------------

class TestResetManifest:
    def test_reset_creates_empty_files_list(self, tmp_path):
        ws = _ws(tmp_path)
        _save_manifest(ws, {DocumentType.other: ["/a.pdf"]})
        reset_manifest(ws)
        data = _load_manifest(ws)
        assert data["files"] == []

    def test_reset_when_no_manifest_does_not_raise(self, tmp_path):
        ws = _ws(tmp_path)
        reset_manifest(ws)  # must not raise


# ---------------------------------------------------------------------------
# chroma_is_current
# ---------------------------------------------------------------------------

class TestChromaIsCurrent:
    def _write_sqlite(self, chroma_dir: Path) -> None:
        chroma_dir.mkdir(parents=True, exist_ok=True)
        (chroma_dir / "chroma.sqlite3").write_bytes(b"fake")

    def test_no_sqlite_returns_false(self, tmp_path):
        ws = _ws(tmp_path)
        classified = {DocumentType.other: ["/a.pdf"]}
        assert chroma_is_current(ws, classified) is False

    def test_no_manifest_returns_false(self, tmp_path):
        ws = _ws(tmp_path)
        self._write_sqlite(Path(ws.chroma))
        classified = {DocumentType.other: ["/a.pdf"]}
        assert chroma_is_current(ws, classified) is False

    def test_matching_files_returns_true(self, tmp_path):
        ws = _ws(tmp_path)
        self._write_sqlite(Path(ws.chroma))
        classified = {DocumentType.lecture_note: ["/a/lec.pdf"]}
        settings = _fake_settings()
        _save_manifest(ws, classified, settings)
        assert chroma_is_current(ws, classified, settings) is True

    def test_file_added_returns_false(self, tmp_path):
        ws = _ws(tmp_path)
        self._write_sqlite(Path(ws.chroma))
        classified = {DocumentType.lecture_note: ["/a.pdf"]}
        settings = _fake_settings()
        _save_manifest(ws, classified, settings)
        classified_new = {DocumentType.lecture_note: ["/a.pdf", "/b.pdf"]}
        assert chroma_is_current(ws, classified_new, settings) is False

    def test_embedding_config_mismatch_returns_false(self, tmp_path):
        ws = _ws(tmp_path)
        self._write_sqlite(Path(ws.chroma))
        classified = {DocumentType.other: ["/a.pdf"]}
        settings_gemini = _fake_settings(provider="gemini")
        _save_manifest(ws, classified, settings_gemini)
        settings_openai = _fake_settings(provider="openai")
        assert chroma_is_current(ws, classified, settings_openai) is False

    def test_without_settings_skips_embedding_check(self, tmp_path):
        ws = _ws(tmp_path)
        self._write_sqlite(Path(ws.chroma))
        classified = {DocumentType.other: ["/a.pdf"]}
        settings = _fake_settings()
        _save_manifest(ws, classified, settings)
        # No settings → embedding check is skipped
        assert chroma_is_current(ws, classified) is True


# ---------------------------------------------------------------------------
# WeightedDocTypeRetriever
# ---------------------------------------------------------------------------

class TestWeightedDocTypeRetriever:
    def _make_vs(self, docs_by_type: dict) -> MagicMock:
        vs = MagicMock()
        def _search(query, k, filter=None):
            if filter is None:
                return [Document(page_content="all", metadata={})]
            dt_val = filter.get("doc_type")
            return docs_by_type.get(dt_val, [])
        vs.similarity_search.side_effect = _search
        return vs

    def test_returns_up_to_k_docs(self):
        docs = [Document(page_content=f"doc{i}", metadata={"doc_type": "syllabus"})
                for i in range(5)]
        vs = self._make_vs({"syllabus": docs})
        retriever = WeightedDocTypeRetriever(
            vectorstore=vs, k=3, weights={"syllabus": 1.0}
        )
        results = retriever._get_relevant_documents("query", run_manager=MagicMock())
        assert len(results) <= 3

    def test_no_weights_falls_back_to_unfiltered(self):
        vs = self._make_vs({})
        retriever = WeightedDocTypeRetriever(vectorstore=vs, k=5, weights={})
        results = retriever._get_relevant_documents("q", run_manager=MagicMock())
        vs.similarity_search.assert_called_once_with("q", k=5)

    def test_deduplicates_across_types(self):
        shared_doc = Document(page_content="shared content", metadata={})
        vs = self._make_vs({
            "syllabus": [shared_doc],
            "lecture_note": [shared_doc],
        })
        retriever = WeightedDocTypeRetriever(
            vectorstore=vs, k=10,
            weights={"syllabus": 1.0, "lecture_note": 1.0},
        )
        results = retriever._get_relevant_documents("q", run_manager=MagicMock())
        # Same content must appear only once
        contents = [r.page_content for r in results]
        assert contents.count("shared content") == 1

    def test_handles_per_type_search_failure_gracefully(self):
        vs = MagicMock()
        vs.similarity_search.side_effect = Exception("filter not supported")
        retriever = WeightedDocTypeRetriever(
            vectorstore=vs, k=5, weights={"past_exam": 2.0}
        )
        # Should not raise
        results = retriever._get_relevant_documents("q", run_manager=MagicMock())
        assert results == []


# ---------------------------------------------------------------------------
# build_weighted_retriever
# ---------------------------------------------------------------------------

class TestBuildWeightedRetriever:
    def test_single_type_returns_plain_retriever(self):
        vs = MagicMock()
        vs.as_retriever.return_value = MagicMock()
        classified = {DocumentType.syllabus: ["/a.pdf"]}
        r = build_weighted_retriever(vs, k=8, task_type=TaskType.review_summary,
                                     classified_files=classified)
        vs.as_retriever.assert_called_once()

    def test_multiple_types_returns_weighted_retriever(self):
        vs = MagicMock()
        vs.as_retriever.return_value = MagicMock()
        classified = {
            DocumentType.syllabus: ["/a.pdf"],
            DocumentType.past_exam: ["/b.pdf"],
        }
        r = build_weighted_retriever(vs, k=8, task_type=TaskType.exam_prediction,
                                     classified_files=classified)
        assert isinstance(r, WeightedDocTypeRetriever)

    def test_empty_classified_returns_plain_retriever(self):
        vs = MagicMock()
        vs.as_retriever.return_value = MagicMock()
        r = build_weighted_retriever(vs, k=8, task_type=TaskType.review_summary,
                                     classified_files={})
        vs.as_retriever.assert_called_once()
