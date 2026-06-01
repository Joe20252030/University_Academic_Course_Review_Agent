"""Tests for agent/workspace_manager.py — wipe operations."""
from __future__ import annotations

from pathlib import Path

import pytest

from uacragent.agent.session import AgentSession
from uacragent.agent.workspace_manager import (
    _safe_rmtree,
    wipe_session_uploads,
    wipe_session_vectorstore,
)
from uacragent.domain.types import DocumentType
from uacragent.infra.workspace import ensure_workspace_dirs, workspace_paths


# ---------------------------------------------------------------------------
# _safe_rmtree (workspace_manager variant)
# ---------------------------------------------------------------------------

class TestSafeRmtreeWM:
    def test_deletes_child_directory(self, tmp_path):
        child = tmp_path / "child"
        child.mkdir()
        (child / "file.txt").write_text("data")
        _safe_rmtree(child, tmp_path)
        assert not child.exists()

    def test_refuses_symlink(self, tmp_path):
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)
        _safe_rmtree(link, tmp_path)
        assert link.exists()
        assert real.exists()

    def test_refuses_path_outside_parent(self, tmp_path):
        sibling = tmp_path.parent / "sibling_wm_test"
        sibling.mkdir(exist_ok=True)
        try:
            _safe_rmtree(sibling, tmp_path)
            assert sibling.exists()
        finally:
            sibling.rmdir()

    def test_no_op_for_file(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("data")
        _safe_rmtree(f, tmp_path)  # must not raise; file is not a dir → no-op
        assert f.exists()


# ---------------------------------------------------------------------------
# wipe_session_uploads
# ---------------------------------------------------------------------------

class TestWipeSessionUploads:
    def _session_with_workspace(self, tmp_path: Path) -> AgentSession:
        ws_folder = tmp_path / "session_ws"
        ws = workspace_paths(workspace_folder=ws_folder)
        ensure_workspace_dirs(ws)
        return AgentSession(workspace_folder=ws_folder, workspace_id="test")

    def test_wipes_typed_upload_folders(self, tmp_path):
        s = self._session_with_workspace(tmp_path)
        ws = workspace_paths(workspace_folder=s.workspace_folder)
        # Populate one typed folder with a file
        lec_folder = ws.doc_folders[DocumentType.lecture_note]
        lec_folder.mkdir(parents=True, exist_ok=True)
        (lec_folder / "notes.txt").write_text("lecture content")

        wipe_session_uploads(s)

        assert not lec_folder.exists()

    def test_no_error_on_empty_session(self):
        s = AgentSession()
        wipe_session_uploads(s)  # must not raise

    def test_no_error_when_upload_folders_do_not_exist(self, tmp_path):
        ws_folder = tmp_path / "fresh_ws"
        ws_folder.mkdir()
        s = AgentSession(workspace_folder=ws_folder, workspace_id="fresh")
        wipe_session_uploads(s)  # must not raise


# ---------------------------------------------------------------------------
# wipe_session_vectorstore
# ---------------------------------------------------------------------------

class TestWipeSessionVectorstore:
    def _session_with_chroma(self, tmp_path: Path) -> AgentSession:
        ws_folder = tmp_path / "chroma_ws"
        ws = workspace_paths(workspace_folder=ws_folder)
        ensure_workspace_dirs(ws)
        # Fake a Chroma DB
        chroma_dir = Path(ws.chroma)
        chroma_dir.mkdir(parents=True, exist_ok=True)
        (chroma_dir / "chroma.sqlite3").write_bytes(b"fake")
        return AgentSession(workspace_folder=ws_folder, workspace_id="chroma-test")

    def test_removes_chroma_directory(self, tmp_path):
        s = self._session_with_chroma(tmp_path)
        ws = workspace_paths(workspace_folder=s.workspace_folder)
        chroma_dir = Path(ws.chroma)
        assert chroma_dir.exists()

        wipe_session_vectorstore(s)

        assert not chroma_dir.exists()

    def test_resets_manifest(self, tmp_path):
        import json
        from uacragent.infra.vectorstore import _manifest_path, _save_manifest

        s = self._session_with_chroma(tmp_path)
        ws = workspace_paths(workspace_folder=s.workspace_folder)
        # Write a non-empty manifest
        _save_manifest(ws, {DocumentType.other: ["/old/file.pdf"]})
        manifest = _manifest_path(ws)
        assert json.loads(manifest.read_text())["files"] != []

        wipe_session_vectorstore(s)

        # Manifest should be reset to empty files list
        data = json.loads(manifest.read_text())
        assert data["files"] == []

    def test_no_error_on_empty_session(self):
        s = AgentSession()
        wipe_session_vectorstore(s)  # must not raise
