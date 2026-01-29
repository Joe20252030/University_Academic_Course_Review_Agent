from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from uacragent.domain.types import DocumentType


@dataclass(frozen=True)
class WorkspacePaths:
    root: Path
    uploads: Path
    chroma: Path
    outputs: Path
    # Classified document folders under uploads/
    doc_folders: dict[DocumentType, Path] = field(default_factory=dict)


def ensure_workspace_dirs(paths: WorkspacePaths) -> None:
    """Create all workspace directories if they don't exist."""
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.uploads.mkdir(parents=True, exist_ok=True)
    paths.outputs.mkdir(parents=True, exist_ok=True)
    paths.chroma.mkdir(parents=True, exist_ok=True)
    # Create classified document folders
    for folder in paths.doc_folders.values():
        folder.mkdir(parents=True, exist_ok=True)


def workspace_paths(
    workspace_root: Path,
    workspace_id: str | None = "default",
) -> WorkspacePaths:
    """Build workspace path structure with classified document folders."""
    if not workspace_id:
        workspace_id = "default"
    ws = workspace_root / workspace_id
    uploads = ws / "uploads"

    # Create a folder for each document type
    doc_folders = {
        doc_type: uploads / doc_type.value
        for doc_type in DocumentType
    }

    return WorkspacePaths(
        root=ws,
        uploads=uploads,
        chroma=ws / "chroma_db",
        outputs=ws / "outputs",
        doc_folders=doc_folders,
    )
