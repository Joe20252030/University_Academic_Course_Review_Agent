"""Tests for workspace path construction and directory creation."""
from __future__ import annotations

from pathlib import Path

import pytest

from uacragent.domain.types import DocumentType
from uacragent.infra.workspace import (
    AGENT_SUBDIR,
    WorkspacePaths,
    ensure_workspace_dirs,
    workspace_paths,
)


def test_workspace_paths_structure(tmp_path: Path):
    ws = workspace_paths(workspace_folder=tmp_path / "myws")
    assert ws.root == tmp_path / "myws"
    assert ws.agent_dir == tmp_path / "myws" / AGENT_SUBDIR
    assert ws.uploads == tmp_path / "myws" / AGENT_SUBDIR / "uploads"
    assert ws.chroma == tmp_path / "myws" / AGENT_SUBDIR / "chroma_db"
    assert ws.outputs == tmp_path / "myws" / AGENT_SUBDIR / "outputs"


def test_workspace_paths_all_doc_types(tmp_path: Path):
    ws = workspace_paths(workspace_folder=tmp_path / "test")
    for doc_type in DocumentType:
        assert doc_type in ws.doc_folders
        assert ws.doc_folders[doc_type] == (
            tmp_path / "test" / AGENT_SUBDIR / "uploads" / doc_type.value
        )


def test_workspace_paths_default_id(tmp_path: Path):
    """workspace_id=None falls back to 'default' subfolder under app data dir."""
    ws = workspace_paths(workspace_id=None)
    assert ws.root.name == "default"


def test_workspace_paths_empty_id(tmp_path: Path):
    """Empty workspace_id string is treated as 'default'."""
    ws = workspace_paths(workspace_id="")
    assert ws.root.name == "default"


def test_workspace_paths_with_managed_base_dir(tmp_path: Path):
    """Managed callers can place workspaces under a dedicated app-owned root."""
    base = tmp_path / "cli_run"
    ws = workspace_paths(workspace_id="abc123", workspace_base_dir=base)
    assert ws.root == base / "abc123"
    assert ws.agent_dir == base / "abc123" / AGENT_SUBDIR


def test_ensure_workspace_dirs_creates_all(tmp_path: Path):
    ws = workspace_paths(workspace_folder=tmp_path / "myws")
    ensure_workspace_dirs(ws)

    assert ws.root.is_dir()
    assert ws.agent_dir.is_dir()
    assert ws.uploads.is_dir()
    assert ws.chroma.is_dir()
    assert ws.outputs.is_dir()
    for folder in ws.doc_folders.values():
        assert folder.is_dir()


def test_ensure_workspace_dirs_idempotent(tmp_path: Path):
    ws = workspace_paths(workspace_folder=tmp_path / "myws")
    ensure_workspace_dirs(ws)
    ensure_workspace_dirs(ws)  # Should not raise


def test_workspace_paths_different_ids_are_isolated(tmp_path: Path):
    ws1 = workspace_paths(workspace_folder=tmp_path / "project_a")
    ws2 = workspace_paths(workspace_folder=tmp_path / "project_b")
    assert ws1.root != ws2.root
    assert ws1.chroma != ws2.chroma
