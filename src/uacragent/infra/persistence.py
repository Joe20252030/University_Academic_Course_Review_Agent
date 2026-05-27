"""Session persistence.

Layout
------
~/.uacragent/                       ← bootstrap location; holds config only
    config.json                     ← stores the user-chosen app data dir

<app_data_dir>/                     ← configurable; defaults to ~/.uacragent
    index.json                      ← lightweight session registry
    models/                         ← HuggingFace model cache (HF_HUB_CACHE)
    sessions/                       ← auto-created workspaces (no user pick)
        <workspace_id>/
            .uacragent/             ← all agent artefacts in one bundle
                session.json
                chroma_db/
                outputs/
                uploads/

<user-chosen workspace>/            ← explicit workspace picked by the user
    .uacragent/                     ← all agent artefacts in one bundle
        session.json                ← full session state (no API key)
        chroma_db/
        outputs/
        uploads/

Rule: the global data folder root contains ONLY index.json and config.json.
All session working data lives inside a workspace's ``.uacragent/`` subdir —
either one the user chose explicitly or one auto-created under
<app_data_dir>/sessions/.  This keeps agent files clearly separated from
any pre-existing files in user-chosen folders.

The API key is intentionally excluded from all saved data.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from uacragent.domain.types import DocumentType

logger = logging.getLogger(__name__)

# Bootstrap location — holds config.json only; never changes.
_UAR_DIR = Path.home() / ".uacragent"
_CONFIG_FILE = _UAR_DIR / "config.json"
_SESSION_FILENAME = "session.json"   # lives inside <workspace>/.uacragent/
_VERSION = 1


# ---------------------------------------------------------------------------
# App-level data directory (global, user-configurable)
# ---------------------------------------------------------------------------

def get_hf_cache_dir() -> Path:
    """Return the directory used for HuggingFace model downloads.

    Kept inside the app data folder so all agent data (index, sessions,
    and local embedding models) lives in one visible place.
    """
    return get_app_data_dir() / "models"


def configure_hf_cache() -> None:
    """Point HuggingFace Hub at the app-managed cache directory.

    Must be called before any ``huggingface_hub`` or ``sentence-transformers``
    import so the env var is in place when those libraries initialise.
    """
    import os
    cache_dir = get_hf_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HUB_CACHE"] = str(cache_dir)


def _load_config() -> dict:
    """Return the parsed ``~/.uacragent/config.json`` dict, or ``{}`` on any error."""
    try:
        if _CONFIG_FILE.exists():
            return json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not read app config: %s", exc)
    return {}


def _save_config(cfg: dict) -> None:
    """Write *cfg* to ``~/.uacragent/config.json``, creating the directory if needed."""
    try:
        _UAR_DIR.mkdir(parents=True, exist_ok=True)
        _CONFIG_FILE.write_text(
            json.dumps(cfg, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("Could not save app config: %s", exc)


def get_app_data_dir() -> Path:
    """Return the user-configured app data directory.

    Reads ``~/.uacragent/config.json``.  Defaults to ``~/.uacragent`` when
    the config is absent or the stored path is empty.
    """
    p = _load_config().get("app_data_dir", "").strip()
    return Path(p) if p else _UAR_DIR


def set_app_data_dir(path: Path) -> None:
    """Persist the chosen app data directory to ``~/.uacragent/config.json``."""
    cfg = _load_config()
    cfg["app_data_dir"] = str(path.resolve())
    _save_config(cfg)


def get_app_appearance() -> dict:
    """Return persisted appearance settings with safe defaults.

    Keys: ``color_mode`` ("light" | "dark"), ``font_size`` ("small" | "medium" | "large"),
    ``language`` ("auto" | "en" | "zh_CN").
    """
    cfg = _load_config()
    return {
        "color_mode": cfg.get("color_mode", "light"),
        "font_size":  cfg.get("font_size",  "medium"),
        "language":   cfg.get("language",   "en"),
    }


def set_app_appearance(color_mode: str, font_size: str, language: str) -> None:
    """Persist appearance settings to ``~/.uacragent/config.json``."""
    cfg = _load_config()
    cfg["color_mode"] = color_mode
    cfg["font_size"]  = font_size
    cfg["language"]   = language
    _save_config(cfg)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _get_index_file() -> Path:
    """Return the index file path inside the current app data directory."""
    return get_app_data_dir() / "index.json"


def _serialise_history(history: list[BaseMessage]) -> list[dict]:
    out = []
    for msg in history:
        if isinstance(msg, HumanMessage):
            out.append({"role": "human", "content": msg.content})
        elif isinstance(msg, AIMessage):
            out.append({"role": "ai", "content": msg.content})
        else:
            logger.warning(
                "Skipping message of unknown type %s during serialisation; "
                "it will not be persisted.",
                type(msg).__name__,
            )
    return out


def _deserialise_history(data: list[dict]) -> list[BaseMessage]:
    msgs: list[BaseMessage] = []
    for item in data:
        role = item.get("role", "")
        content = item.get("content", "")
        if role == "human":
            msgs.append(HumanMessage(content=content))
        elif role == "ai":
            msgs.append(AIMessage(content=content))
        else:
            logger.warning(
                "Skipping message with unknown role %r during deserialisation.",
                role,
            )
    # Guard: history must have an even number of messages (human+ai pairs).
    # A dangling message (odd length) indicates a serialisation bug; drop the
    # last message so the history stays correctly paired.
    if len(msgs) % 2 != 0:
        logger.warning(
            "Deserialised chat history has odd number of messages (%d); "
            "dropping last dangling message to keep history paired.",
            len(msgs),
        )
        msgs = msgs[:-1]
    return msgs


def _serialise_files(classified: dict[DocumentType, list[str]]) -> dict[str, list[str]]:
    return {dt.value: paths for dt, paths in classified.items()}


def _deserialise_files(data: dict[str, list[str]]) -> dict[DocumentType, list[str]]:
    result: dict[DocumentType, list[str]] = {}
    for key, paths in data.items():
        try:
            dt = DocumentType(key)
        except ValueError:
            continue
        valid = [p for p in paths if Path(p).exists()]
        if valid:   # omit empty buckets — they only add noise to session state
            result[dt] = valid
    return result


def get_missing_session_files(data: dict) -> list[str]:
    """Return a list of file paths stored in *data* that no longer exist on disk.

    Call this after ``load_session()`` to detect files that were saved in a
    previous session but have since been moved or deleted.  The list is empty
    when all recorded files are still present.
    """
    missing: list[str] = []
    for paths in data.get("classified_files", {}).values():
        for p in paths:
            if p and not Path(p).exists():
                missing.append(p)
    return missing


# ---------------------------------------------------------------------------
# Index helpers
# ---------------------------------------------------------------------------

def _load_index() -> list[dict]:
    """Return the list of session metadata records."""
    index_file = _get_index_file()
    if not index_file.exists():
        return []
    try:
        return json.loads(index_file.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not read session index: %s", exc)
        return []


def _save_index(records: list[dict]) -> None:
    try:
        data_dir = get_app_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        _get_index_file().write_text(
            json.dumps(records, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("Could not write session index: %s", exc)


def _upsert_index(workspace: Path, course_name: str) -> None:
    """Insert or update the index entry for *workspace*."""
    records = _load_index()
    ws_str = str(workspace.resolve())
    for rec in records:
        if rec.get("workspace") == ws_str:
            rec["course_name"] = course_name
            rec["last_modified"] = _now_iso()
            break
    else:
        records.append({
            "workspace": ws_str,
            "course_name": course_name,
            "last_modified": _now_iso(),
        })
    _save_index(records)


def rename_session(workspace: Path, new_name: str) -> None:
    """Set a custom display name for the session at *workspace*.

    The display_name is stored in the index only and is purely cosmetic —
    it does not affect the course_name used in prompts.
    """
    records = _load_index()
    ws_str = str(workspace.resolve())
    for rec in records:
        if rec.get("workspace") == ws_str:
            rec["display_name"] = new_name.strip()
            rec["last_modified"] = _now_iso()
            break
    _save_index(records)


def _remove_from_index(workspace: Path) -> None:
    ws_str = str(workspace.resolve())
    records = [r for r in _load_index() if r.get("workspace") != ws_str]
    _save_index(records)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_sessions() -> list[dict]:
    """Return session metadata records sorted newest-first.

    Each record: ``{workspace, course_name, last_modified}``
    Workspace paths in the records are always the resolved (canonical) form.
    """
    from uacragent.infra.workspace import AGENT_SUBDIR

    records = _load_index()
    # Filter out entries whose session file no longer exists
    def _session_exists(r: dict) -> bool:
        ws = r.get("workspace", "")
        if not ws:
            return False
        return (Path(ws) / AGENT_SUBDIR / _SESSION_FILENAME).exists()

    valid = [r for r in records if _session_exists(r)]
    if len(valid) != len(records):
        _save_index(valid)
    return sorted(valid, key=lambda r: r.get("last_modified", ""), reverse=True)


def save_session(
    session: "AgentSession",  # type: ignore[name-defined]
    ui_extras: dict | None = None,
) -> bool:
    """Serialise *session* to ``<workspace>/.uacragent/session.json`` and update the index.

    All agent artefacts live inside the ``.uacragent`` subdirectory so they
    form a single, clearly-labelled bundle inside the user's workspace.
    The API key is never written.

    Returns
    -------
    bool
        ``True`` on success, ``False`` if the file could not be written
        (e.g. disk full, permission denied).  The caller is responsible for
        surfacing a visible error to the user when ``False`` is returned.
    """
    from uacragent.infra.workspace import AGENT_SUBDIR

    workspace = _resolve_workspace(session)
    agent_dir = workspace / AGENT_SUBDIR
    agent_dir.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "version": _VERSION,
        "llm_provider": session.llm_provider,
        "llm_model": session.llm_model,
        "course_name": session.course_name,
        "university_name": session.university_name,
        "major": session.major,
        "course_code": session.course_code,
        "professor_name": session.professor_name,
        "semester": session.semester,
        "exam_type": session.exam_type,
        "exam_format": session.exam_format,
        "exam_duration": session.exam_duration,
        "exam_info_path": session.exam_info_path,
        "workspace_id": session.workspace_id,
        "workspace_folder": str(workspace),
        "extra_instructions": session.extra_instructions,
        "classified_files": _serialise_files(session.classified_files),
        "chat_history": _serialise_history(session.chat_history),
        "history_summary": session.history_summary,
    }
    # Defensive key-name blocklist: cover every name a caller might accidentally
    # pass, now and in the future.  API keys are NEVER written to disk.
    _KEY_NAMES = frozenset({
        "api_key", "google_api_key", "openai_api_key", "deepseek_api_key",
        "GOOGLE_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY",
        "key", "secret", "token", "password",
    })
    if ui_extras:
        payload.update({k: v for k, v in ui_extras.items()
                        if k not in _KEY_NAMES})

    try:
        session_file = agent_dir / _SESSION_FILENAME
        session_file.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        _upsert_index(workspace, session.course_name or str(workspace.name))
        return True
    except Exception as exc:
        logger.warning("Could not save session to %s: %s", workspace, exc)
        return False


def load_session(workspace: Path) -> dict[str, Any] | None:
    """Load session state from ``<workspace>/.uacragent/session.json``.

    Returns
    -------
    dict
        The parsed session payload on success.
    dict with ``_version_mismatch=True``
        When the file exists but was written by a different app version.
        Callers can detect this via ``data.get("_version_mismatch")``.
    None
        When the session file does not exist or could not be parsed.
    """
    from uacragent.infra.workspace import AGENT_SUBDIR

    session_file = workspace / AGENT_SUBDIR / _SESSION_FILENAME
    if not session_file.exists():
        return None
    try:
        raw = json.loads(session_file.read_text(encoding="utf-8"))
        if raw.get("version") != _VERSION:
            logger.warning(
                "Session version mismatch in %s (file version=%s, expected=%s) — "
                "cannot restore session state.",
                workspace, raw.get("version"), _VERSION,
            )
            return {"_version_mismatch": True, "workspace_folder": str(workspace)}
        return raw
    except Exception as exc:
        logger.warning("Could not load session from %s: %s", workspace, exc)
        return None


def delete_session(workspace: Path) -> None:
    """Delete all agent-created files inside *workspace* and remove from index.

    All agent artefacts live inside ``<workspace>/.uacragent/``, so deletion
    is simply a matter of wiping that single subdirectory.

    The workspace folder itself is removed only when it is empty afterwards
    (i.e. it was auto-created solely by the agent).  User-chosen folders that
    contain other files are left in place.
    """
    import shutil
    from uacragent.infra.workspace import AGENT_SUBDIR

    agent_dir = workspace / AGENT_SUBDIR
    try:
        if agent_dir.is_dir():
            shutil.rmtree(agent_dir)
    except Exception as exc:
        logger.warning("Could not remove agent dir %s: %s", agent_dir, exc)

    # Remove the workspace folder itself if it is now effectively empty.
    #
    # "Effectively empty" means the only surviving items are OS-generated
    # metadata files (macOS .DS_Store, Windows Thumbs.db / desktop.ini).
    # Those are invisible to the user and safe to delete together with the
    # parent folder.  Any real user file keeps the workspace folder alive.
    _OS_METADATA: frozenset[str] = frozenset({
        ".DS_Store", ".localized", "Thumbs.db", "desktop.ini", ".Spotlight-V100",
    })
    try:
        if workspace.exists():
            user_items = [p for p in workspace.iterdir() if p.name not in _OS_METADATA]
            if not user_items:
                shutil.rmtree(workspace)
    except Exception as exc:
        logger.warning("Could not remove workspace folder %s: %s", workspace, exc)

    _remove_from_index(workspace)


def dict_to_session(data: dict[str, Any]) -> "AgentSession":  # type: ignore[name-defined]
    """Reconstruct an AgentSession from a persisted dict."""
    from uacragent.agent.session import AgentSession

    wf_str = data.get("workspace_folder", "")
    workspace_folder = Path(wf_str) if wf_str else None

    import uuid as _uuid
    # Guard against empty workspace_id (e.g. a session.json written with
    # "workspace_id": "").  An empty string would collapse in _resolve_workspace
    # to the shared sessions/default path, corrupting unrelated sessions.
    workspace_id = data.get("workspace_id", "") or _uuid.uuid4().hex[:12]

    return AgentSession(
        llm_provider=data.get("llm_provider", "gemini"),
        llm_model=data.get("llm_model", "gemini-2.5-flash"),
        course_name=data.get("course_name", ""),
        university_name=data.get("university_name", ""),
        major=data.get("major", ""),
        course_code=data.get("course_code", ""),
        professor_name=data.get("professor_name", ""),
        semester=data.get("semester", ""),
        exam_type=data.get("exam_type", "final"),
        exam_format=data.get("exam_format", "written"),
        exam_duration=data.get("exam_duration", ""),
        exam_info_path=data.get("exam_info_path", ""),
        workspace_id=workspace_id,
        workspace_folder=workspace_folder,
        extra_instructions=data.get("extra_instructions", ""),
        classified_files=_deserialise_files(data.get("classified_files", {})),
        chat_history=_deserialise_history(data.get("chat_history", [])),
        history_summary=data.get("history_summary", ""),
    )


# ---------------------------------------------------------------------------
# Internal utility
# ---------------------------------------------------------------------------

def _resolve_workspace(session: "AgentSession") -> Path:  # type: ignore[name-defined]
    """Return the absolute workspace folder for *session*.

    Priority:
    1. session.workspace_folder — set by the user via folder picker or
       auto-assigned on first Apply; locked thereafter.
    2. <app_data_dir>/sessions/<workspace_id> — auto-created fallback,
       kept inside a dedicated ``sessions/`` subfolder so the global data
       folder root stays clean (only index.json and config.json live there).
    """
    if session.workspace_folder:
        return session.workspace_folder.resolve()
    return (get_app_data_dir() / "sessions" / (session.workspace_id or "default")).resolve()
