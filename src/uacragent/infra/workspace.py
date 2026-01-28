from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class WorkspacePaths:
    root: Path
    uploads: Path
    chroma: Path
    outputs: Path

def ensure_workspace_dirs(paths: WorkspacePaths) -> None:
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.uploads.mkdir(parents=True, exist_ok=True)
    paths.outputs.mkdir(parents=True, exist_ok=True)
    paths.chroma.mkdir(parents=True, exist_ok=True)

def workspace_paths(
    workspace_root: Path,
    workspace_id: str | None = "default",
) -> WorkspacePaths:
    if not workspace_id:
        workspace_id = "default"
    ws = workspace_root / workspace_id
    return WorkspacePaths(
        root=ws,
        uploads=ws / "uploads",
        chroma=ws / "chroma_db",
        outputs=ws / "outputs",
    )
