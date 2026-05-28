from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from uacragent.domain.errors import ConfigurationError
from uacragent.domain.types import DocumentType

# Only alphanumeric characters, hyphens, and underscores are allowed in a
# workspace_id.  This prevents path-traversal attacks when the id is
# appended to the app data directory (e.g. workspace_id = "../../etc").
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

# All agent-created working data lives inside this subdirectory of the
# user-chosen (or auto-generated) workspace folder.  This keeps agent
# artefacts clearly separated from any pre-existing user files.
AGENT_SUBDIR = ".uacragent"


@dataclass(frozen=True)
class WorkspacePaths:
    root: Path          # workspace folder chosen / assigned for the session
    agent_dir: Path     # <root>/.uacragent — all agent data lives here
    uploads: Path
    chroma: Path
    outputs: Path
    # Classified document folders under uploads/
    doc_folders: dict[DocumentType, Path] = field(default_factory=dict)


def ensure_workspace_dirs(paths: WorkspacePaths) -> None:
    """Create all workspace directories if they don't exist.

    Raises :class:`~uacragent.domain.errors.ConfigurationError` when any
    directory cannot be created (e.g. read-only volume, disk quota exceeded).
    The caller can catch this and surface a user-readable message rather than
    letting a bare ``OSError`` propagate into the chat panel.
    """
    dirs = [
        paths.agent_dir,
        paths.uploads,
        paths.outputs,
        paths.chroma,
        *paths.doc_folders.values(),
    ]
    for d in dirs:
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ConfigurationError(
                f"Cannot create workspace directory '{d}': {exc}.\n"
                "Check that the workspace location is writable and that you "
                "have sufficient disk space."
            ) from exc


def workspace_paths(
    workspace_id: str | None = None,
    *,
    workspace_folder: Path | None = None,
) -> WorkspacePaths:
    """Build workspace path structure.

    Resolution order
    ----------------
    1. *workspace_folder* — used directly as the workspace root when provided.
       This is the normal path for any session that has been committed.
    2. ``get_app_data_dir()`` / *workspace_id* — default: auto folder inside
       the user-configured app data directory.

    All agent artefacts (uploads, chroma_db, outputs, session.json) are
    placed inside ``<workspace>/.uacragent/`` so they form a single,
    clearly-labelled bundle that does not mix with the user's own files.
    """
    if workspace_folder is not None:
        # Resolve to an absolute canonical path so symlinks and relative
        # components (e.g. "..") cannot escape the intended directory.
        ws = Path(workspace_folder).resolve()
    else:
        from uacragent.infra.persistence import get_app_data_dir
        safe_id = workspace_id or "default"
        if not _SAFE_ID_RE.match(safe_id):
            from uacragent.domain.errors import ConfigurationError
            raise ConfigurationError(
                f"Invalid workspace_id {safe_id!r}: only letters, digits, "
                "hyphens, and underscores are allowed (max 128 chars)."
            )
        ws = get_app_data_dir() / safe_id

    agent_dir = ws / AGENT_SUBDIR
    uploads = agent_dir / "uploads"
    doc_folders = {
        doc_type: uploads / doc_type.value
        for doc_type in DocumentType
    }

    return WorkspacePaths(
        root=ws,
        agent_dir=agent_dir,
        uploads=uploads,
        chroma=agent_dir / "chroma_db",
        outputs=agent_dir / "outputs",
        doc_folders=doc_folders,
    )
