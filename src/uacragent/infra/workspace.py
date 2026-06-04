from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from uacragent.domain.errors import ConfigurationError
from uacragent.domain.types import DocumentType

logger = logging.getLogger(__name__)

# Only alphanumeric characters, hyphens, and underscores are allowed in a
# workspace_id.  This prevents path-traversal attacks when the id is
# appended to the app data directory (e.g. workspace_id = "../../etc").
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

# All agent-created working data lives inside this subdirectory of the
# user-chosen (or auto-generated) workspace folder.  This keeps agent
# artefacts clearly separated from any pre-existing user files.
AGENT_SUBDIR = ".uacragent"

# ---------------------------------------------------------------------------
# Filesystem safety helpers
# ---------------------------------------------------------------------------

def _safe_rmtree(path: Path, expected_parent: Path) -> None:
    """Delete *path* only when it is a real directory under *expected_parent*.

    Refuses deletion when:
    * ``path`` resolves outside *expected_parent* (path-escape guard).
    * ``path`` is a symlink — rmtree would follow it and wipe the link target,
      which could be an arbitrary location on disk.

    Both refusals are logged as warnings.
    """
    resolved = path.resolve()
    parent_resolved = expected_parent.resolve()
    try:
        resolved.relative_to(parent_resolved)
    except ValueError:
        logger.warning(
            "rmtree refused: %s is not under expected parent %s",
            path, expected_parent,
        )
        return
    if path.is_symlink():
        logger.warning("rmtree refused: %s is a symlink", path)
        return
    if not path.is_dir():
        return
    shutil.rmtree(path)


# ---------------------------------------------------------------------------
# Ownership marker
# ---------------------------------------------------------------------------
# Every .uacragent/ directory created or first-saved by UACRAgent contains
# an owner.json file.  Destructive operations (wipe uploads, wipe vectorstore,
# delete session) check for this marker before touching anything on disk.
#
# This protects users who select a custom workspace that already contains a
# .uacragent/ folder created by another tool: without the marker, we refuse to
# delete or wipe, preventing accidental data loss.
#
# Migration path for pre-0.4.0 sessions (no owner.json yet):
#   - ensure_workspace_dirs() writes the marker when agent_dir contains
#     session.json (proof it was created by UACRAgent in an earlier version).
#   - save_session() writes the marker unconditionally after each successful
#     save, so any surviving old session is adopted on its first save.

OWNER_MARKER_FILENAME = "owner.json"
_OWNER_APP_TAG        = "uacragent"


def write_ownership_marker(
    agent_dir: Path,
    workspace_id: str | None = None,
) -> bool:
    """Write ``owner.json`` into *agent_dir* to record UACRAgent ownership.

    Idempotent: returns ``True`` immediately if the marker already exists.

    Returns
    -------
    True
        Marker was written successfully (or already existed).
    False
        Write failed.  The caller decides whether to treat this as fatal:
        fresh-creation paths should raise; migration/belt-and-suspenders
        paths may log and continue.
    """
    marker_path = agent_dir / OWNER_MARKER_FILENAME
    if marker_path.exists():
        return True
    try:
        from importlib.metadata import version as _iv
        _ver = _iv("uacragent")
    except Exception:  # noqa: BLE001
        _ver = "unknown"
    payload = {
        "app":          _OWNER_APP_TAG,
        "version":      _ver,
        "created_at":   datetime.now(timezone.utc).isoformat(),
        "workspace_id": workspace_id or "",
    }
    try:
        agent_dir.mkdir(parents=True, exist_ok=True)
        marker_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not write ownership marker in %s: %s", agent_dir, exc)
        return False


def has_ownership_marker(agent_dir: Path) -> bool:
    """Return True when *agent_dir* contains a valid UACRAgent ownership marker.

    A marker is valid when ``owner.json`` exists and its ``"app"`` field equals
    ``"uacragent"``.  Any missing file, I/O error, or unrecognised content
    returns False — the caller should treat the folder as unowned.
    """
    marker_path = agent_dir / OWNER_MARKER_FILENAME
    if not marker_path.is_file():
        return False
    try:
        data = json.loads(marker_path.read_text(encoding="utf-8"))
        return data.get("app") == _OWNER_APP_TAG
    except Exception:  # noqa: BLE001
        return False


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
    """Create all workspace directories if they don't exist, then claim
    ownership of ``agent_dir`` when appropriate.

    Raises :class:`~uacragent.domain.errors.ConfigurationError` when:

    * Any directory cannot be created (e.g. read-only volume, disk quota).
    * ``agent_dir`` already exists, is not owned by UACRAgent, and has no
      ``session.json`` migration marker — creating children inside an
      unrecognised folder would silently modify data that is not ours.
    * ``agent_dir`` was freshly created but the ownership marker could not
      be written — this would leave app data in a folder we cannot later
      manage or clean up.

    Ownership marker logic
    ----------------------
    1. ``agent_dir`` did **not** exist before this call — we created it, so
       it is unambiguously ours.  Marker write is **required** (fatal on
       failure).

    2. ``agent_dir`` existed **and** has ``owner.json`` — already claimed,
       nothing to do.

    3. ``agent_dir`` existed **and** has ``session.json`` but no ``owner.json``
       — pre-0.4.0 migration case.  Marker write is best-effort (non-fatal).

    4. ``agent_dir`` existed, no ``owner.json``, no ``session.json`` — foreign
       folder.  Raise ``ConfigurationError`` immediately without creating any
       children inside it.
    """
    agent_dir_existed = paths.agent_dir.exists()
    _session_json     = paths.agent_dir / "session.json"

    # ── Ownership pre-check (only relevant when agent_dir already exists) ──
    if agent_dir_existed:
        _already_owned = has_ownership_marker(paths.agent_dir)
        _migratable    = _session_json.is_file()

        if not _already_owned and not _migratable:
            # The directory exists and is neither owned by us nor a legacy
            # UACRAgent session we can migrate.  Refuse to create any child
            # directories inside it — this protects the user's pre-existing
            # content from unexpected modification.
            raise ConfigurationError(
                f"The directory '{paths.agent_dir}' already exists but does "
                "not have an UACRAgent ownership marker (owner.json) and does "
                "not contain a session.json that would identify it as a "
                "pre-existing UACRAgent session.\n\n"
                "Creating workspace files inside an unrecognised folder could "
                "modify data that does not belong to this application.\n\n"
                "Please choose a different workspace folder, or manually remove "
                f"'{paths.agent_dir}' if it is safe to do so."
            )

    # ── Create all required directories ───────────────────────────────────
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

    # ── Write ownership marker ────────────────────────────────────────────
    if not agent_dir_existed:
        # Case 1: freshly created — marker is required.
        # If it cannot be written, the folder is app-created but unclaimable;
        # future cleanup would permanently refuse to manage it.  Fail now so
        # the user sees a clear error rather than accumulating ghost workspaces.
        if not write_ownership_marker(paths.agent_dir):
            raise ConfigurationError(
                f"Could not write the UACRAgent ownership marker to "
                f"'{paths.agent_dir}'.\n"
                "The workspace directory was created but cannot be claimed. "
                "Check that the folder is writable and that the disk is not full."
            )
    elif _session_json.is_file() and not has_ownership_marker(paths.agent_dir):
        # Case 3: migration — best-effort, non-fatal.
        write_ownership_marker(paths.agent_dir)


def workspace_paths(
    workspace_id: str | None = None,
    *,
    workspace_folder: Path | None = None,
    workspace_base_dir: Path | None = None,
) -> WorkspacePaths:
    """Build workspace path structure.

    Resolution order
    ----------------
    1. *workspace_folder* — used directly as the workspace root when provided.
       This is the normal path for any session that has been committed.
    2. *workspace_base_dir* / *workspace_id* — managed auto folder inside a
       caller-selected app-owned subdirectory such as ``sessions/``,
       ``cli_run/``, or ``api_run/``.
    3. ``get_app_data_dir()`` / *workspace_id* — legacy default when no
       explicit base directory is supplied.

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
        base_dir = Path(workspace_base_dir).resolve() if workspace_base_dir is not None else get_app_data_dir()
        ws = base_dir / safe_id

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
