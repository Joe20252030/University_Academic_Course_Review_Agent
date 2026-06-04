"""Session workspace cleanup utilities.

Functions that wipe parts of a session's workspace (uploaded files, vector
store) are collected here so the logic is not duplicated across the pipeline
and conversation layers.

Public API
----------
wipe_session_uploads(session)
    Delete all typed upload subfolders for the session's workspace.
wipe_session_vectorstore(session)
    Delete the Chroma vector store and reset the indexed-files manifest.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from uacragent.infra.workspace import _safe_rmtree  # noqa: E402


def wipe_session_uploads(session: "AgentSession") -> None:  # type: ignore[name-defined]
    """Delete all typed upload subfolders for *session*'s workspace.

    Called on every full re-index (Apply) so that workspace copies of files
    the user removed via the GUI are actually deleted from disk before the
    current file set is re-copied.  Also called directly when the user removes
    every file and clicks Apply — in that case the main pipeline is never
    entered, so the cleanup must happen at a higher level.

    Safe to call on a freshly-created session that has never been indexed.

    Ownership guard
    ---------------
    If the workspace's ``.uacragent/`` directory exists but does **not** contain
    a valid ``owner.json`` marker, the wipe is skipped.  This prevents accidental
    deletion of files inside a ``.uacragent/`` folder that was not created by
    UACRAgent (e.g. a pre-existing folder in a user-chosen custom workspace).
    The marker is written by ``ensure_workspace_dirs()`` and ``save_session()``,
    so any legitimate UACRAgent session will have it after the first Apply.
    """
    if not session.workspace_id and not session.workspace_folder:
        return
    try:
        from uacragent.infra.workspace import workspace_paths, has_ownership_marker
        ws = workspace_paths(
            workspace_id=session.workspace_id,
            workspace_folder=session.workspace_folder,
        )
        if not has_ownership_marker(ws.agent_dir):
            logger.warning(
                "Skipping upload wipe for '%s': ownership marker (owner.json) "
                "missing. The .uacragent/ folder may not have been created by "
                "UACRAgent. No files will be deleted.",
                ws.agent_dir,
            )
            return
        for folder in ws.doc_folders.values():
            if folder.exists():
                _safe_rmtree(folder, ws.uploads)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not wipe session uploads: %s", exc)


def wipe_session_vectorstore(session: "AgentSession") -> None:  # type: ignore[name-defined]
    """Delete the Chroma vector store and reset the indexed-files manifest.

    Called when the user removes **all** files and clicks Apply.  Without this,
    the old chroma_db and its manifest linger on disk even though no documents
    are associated with the session, wasting disk space and causing the
    manifest to misreport a stale file set on the next indexing run.

    Safe to call when the chroma_db or manifest do not exist yet.

    Ownership guard
    ---------------
    Same as :func:`wipe_session_uploads` — the wipe is skipped when the
    ownership marker is absent.
    """
    if not session.workspace_id and not session.workspace_folder:
        return
    try:
        from uacragent.infra.workspace import workspace_paths, has_ownership_marker
        from uacragent.infra.vectorstore import reset_manifest
        ws = workspace_paths(
            workspace_id=session.workspace_id,
            workspace_folder=session.workspace_folder,
        )
        if not has_ownership_marker(ws.agent_dir):
            logger.warning(
                "Skipping vectorstore wipe for '%s': ownership marker missing.",
                ws.agent_dir,
            )
            return
        # Wipe the Chroma directory
        chroma_dir = Path(ws.chroma)
        if chroma_dir.exists():
            _safe_rmtree(chroma_dir, ws.agent_dir)
        # Reset the manifest to an empty file set so the next indexing run
        # starts from a clean slate rather than comparing against stale paths.
        reset_manifest(ws)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not wipe session vectorstore: %s", exc)
