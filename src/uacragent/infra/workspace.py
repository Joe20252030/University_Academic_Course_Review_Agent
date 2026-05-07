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
    for folder in paths.doc_folders.values():
        folder.mkdir(parents=True, exist_ok=True)


def workspace_paths(
    workspace_root: Path | None = None,
    workspace_id: str | None = None,
    *,
    workspace_folder: Path | None = None,
) -> WorkspacePaths:
    """Build workspace path structure.

    Resolution order
    ----------------
    1. *workspace_folder* — used directly as the workspace root when provided.
       This is the normal path for any session that has been committed.
    2. *workspace_root* / *workspace_id* — legacy / programmatic override.
    3. ``get_app_data_dir()`` / *workspace_id* — default: auto folder inside
       the user-configured app data directory.
    """
    if workspace_folder is not None:
        ws = Path(workspace_folder)
    else:
        if workspace_root is None:
            from uacragent.infra.persistence import get_app_data_dir
            workspace_root = get_app_data_dir()
        ws = workspace_root / (workspace_id or "default")

    uploads = ws / "uploads"
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
