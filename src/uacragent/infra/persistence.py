"""Session persistence.

Layout
------
~/.uacragent/                       ← bootstrap location; holds config only
    config.json                     ← stores the user-chosen app data dir

<app_data_dir>/                     ← configurable; defaults to ~/.uacragent
    index.json                      ← lightweight session registry
    models/                         ← app-managed local model cache root
        chroma/onnx_models/         ← frozen-app ONNX embedding downloads
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

Rule: the global data folder root contains only index.json, logs/, models/,
and chroma_telemetry_user_id.  All session working data lives inside a
workspace's ``.uacragent/`` subdir — either one the user chose explicitly or
one auto-created under <app_data_dir>/sessions/.  This keeps agent files
clearly separated from any pre-existing files in user-chosen folders.

The API key is intentionally excluded from all saved data.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
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


def get_chroma_onnx_models_dir() -> Path:
    """Return the app-managed root for Chroma's ONNX embedding downloads."""
    return get_hf_cache_dir() / "chroma" / "onnx_models"


def get_chroma_onnx_model_dir(model_name: str = "all-MiniLM-L6-v2") -> Path:
    """Return the app-managed folder for a specific Chroma ONNX model."""
    return get_chroma_onnx_models_dir() / model_name


def _configure_chroma_onnx_cache() -> None:
    """Redirect Chroma's ONNX embedding download path into the app data dir."""
    cache_root = get_chroma_onnx_models_dir()
    cache_root.mkdir(parents=True, exist_ok=True)
    try:
        from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import (
            ONNXMiniLM_L6_V2,
        )
    except Exception:
        return

    ONNXMiniLM_L6_V2.DOWNLOAD_PATH = get_chroma_onnx_model_dir(
        ONNXMiniLM_L6_V2.MODEL_NAME
    )


def configure_hf_cache() -> None:
    """Point local-model downloads at app-managed cache directories.

    Must be called before any ``huggingface_hub`` or ``sentence-transformers``
    import so the env var is in place when those libraries initialise.
    Also redirects Chroma's frozen-app ONNX model download path into the same
    app-managed models tree, and disables Chroma's anonymized telemetry so it
    does not create side files outside the app-managed folders.
    """
    import os
    cache_dir = get_hf_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Set all HuggingFace cache env vars so every HF/transformers/sentence-
    # transformers code path — including legacy ones that pre-date HF_HUB_CACHE
    # — writes into the app-managed directory rather than ~/.cache/huggingface/.
    os.environ["HF_HUB_CACHE"]           = str(cache_dir)
    os.environ["HF_HOME"]                 = str(cache_dir)
    os.environ["TRANSFORMERS_CACHE"]      = str(cache_dir)
    os.environ["SENTENCE_TRANSFORMERS_HOME"] = str(cache_dir)
    os.environ["ANONYMIZED_TELEMETRY"] = "FALSE"
    # Prevent HuggingFace tokenizer fork-safety warnings / deadlocks when the
    # app forks (e.g. macOS multiprocessing).  Must be set before tokenisers
    # are first imported.
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    _configure_chroma_onnx_cache()
    _redirect_chroma_telemetry_file()


def _redirect_chroma_telemetry_file() -> None:
    """Redirect ChromaDB's telemetry UUID file into the app data directory.

    ChromaDB's ``Posthog`` client writes a one-time UUID to
    ``~/.cache/chroma/telemetry_user_id`` the first time a ``Chroma(...)``
    client is constructed — even when ``anonymized_telemetry=False``.

    The root cause: ``_direct_capture`` evaluates ``self.user_id`` as a Python
    argument expression *before* ``posthog.capture()`` can check
    ``posthog.disabled`` and short-circuit.  No data is ever transmitted
    (the network call is suppressed), but the UUID file lands outside the
    app-managed directory tree.

    Fix: patch the ``USER_ID_PATH`` class attribute to a path inside
    ``<app_data_dir>/`` so the file stays within the expected boundary.
    Must be called before any ``Chroma(...)`` construction.
    """
    try:
        from chromadb.telemetry.product.posthog import Posthog
        Posthog.USER_ID_PATH = str(get_app_data_dir() / "chroma_telemetry_user_id")
    except Exception:
        # chromadb not installed or telemetry class moved — safe to ignore.
        pass


# ---------------------------------------------------------------------------
# Application logging
# ---------------------------------------------------------------------------

# Third-party loggers that are extremely verbose at DEBUG / INFO.  We clamp
# them to WARNING so they don't flood the log file with routine HTTP traces,
# tokeniser progress bars, or ChromaDB heartbeat messages.
_NOISY_LOGGERS: tuple[str, ...] = (
    "httpx", "httpcore", "httpcore.http11", "httpcore.connection",
    "openai", "openai._base_client",
    "anthropic",
    "google", "google.auth", "google.api_core",
    "langchain", "langchain_core", "langchain_community",
    "langchain_google_genai", "langchain_openai",
    "chromadb", "chromadb.telemetry",
    "sentence_transformers",
    "huggingface_hub", "huggingface_hub.utils",
    "transformers",
    "posthog",
    "PIL",
    "urllib3", "urllib3.connectionpool",
    "asyncio",
)


class _ResilientRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """RotatingFileHandler that reopens the log file if it was deleted at runtime.

    The standard ``RotatingFileHandler`` keeps the file descriptor open.  On
    Unix/macOS, deleting the file while the app is running leaves the fd valid
    (the kernel keeps the inode alive), so writes silently succeed but go
    nowhere on disk — the data is lost when the process closes the fd.

    This subclass checks on every ``emit()`` whether the file still exists on
    disk under the same path.  If it has been deleted (or moved), the stream
    is closed and reopened, creating a fresh file.  The overhead is a single
    ``os.path.exists`` call per log record — negligible for WARNING-level
    logging.
    """

    def emit(self, record: logging.LogRecord) -> None:
        # Only check when the stream is already open (i.e. after the first
        # write).  Before that, delay=True means self.stream is None and the
        # normal open path handles creation.
        if self.stream is not None and not Path(self.baseFilename).exists():
            try:
                self.stream.close()
            except Exception:  # noqa: BLE001
                pass
            self.stream = None  # force _open() on next emit via superclass
        super().emit(record)


def configure_logging() -> None:
    """Configure application-wide logging to a rotating file in the app data dir.

    Layout
    ------
    ``<app_data_dir>/logs/uacragent.log``   — current log file
    ``<app_data_dir>/logs/uacragent.log.1`` — previous rotation
    ``<app_data_dir>/logs/uacragent.log.2`` — two rotations back

    Each file is capped at 2 MB; three files are kept, giving ~6 MB maximum.
    The current log file is created eagerly at startup so users have a stable
    path to inspect even before the first warning/error is emitted. If the user
    deletes the log file while the app is running, the next log message
    recreates it automatically (no restart required).

    Level
    -----
    ``WARNING`` by default — captures all warnings and errors without drowning
    the file in routine debug traces from LangChain / ChromaDB / httpx etc.
    Set the environment variable ``UACRAGENT_LOG_LEVEL=DEBUG`` before launch to
    enable verbose output (useful when diagnosing indexing or embedding issues).

    Third-party noise
    -----------------
    Verbose libraries (httpx, langchain, chromadb, huggingface_hub, …) are
    clamped to ``WARNING`` individually so they don't flood the file even when
    the root level is set to ``DEBUG``.

    Idempotency
    -----------
    Safe to call more than once — subsequent calls are no-ops so test suites
    that import the app multiple times do not accumulate duplicate handlers.
    """
    import os

    root = logging.getLogger()

    # Idempotency: skip if our handler is already attached.
    if any(isinstance(h, _ResilientRotatingFileHandler) for h in root.handlers):
        return

    # ── Log directory ─────────────────────────────────────────────────────────
    log_dir = get_app_data_dir() / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # If we can't create the log directory (e.g. permissions), fall back
        # to the bootstrap ~/.uacragent/logs so we still get some output.
        log_dir = _UAR_DIR / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return  # truly unable to write logs — give up silently

    log_file = log_dir / "uacragent.log"
    try:
        log_file.touch(exist_ok=True)
    except OSError:
        pass

    # ── Level ─────────────────────────────────────────────────────────────────
    level_name = os.environ.get("UACRAGENT_LOG_LEVEL", "WARNING").upper()
    level = getattr(logging, level_name, logging.WARNING)

    # ── File handler (resilient rotating, 2 MB × 3 files) ────────────────────
    try:
        file_handler = _ResilientRotatingFileHandler(
            log_file,
            maxBytes=2 * 1024 * 1024,   # 2 MB per file
            backupCount=3,
            encoding="utf-8",
            delay=True,                  # don't create the file until first write
        )
    except OSError:
        return  # can't open the log file — give up silently

    fmt = logging.Formatter(
        fmt="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(level)

    # ── Root logger ───────────────────────────────────────────────────────────
    root.setLevel(level)
    root.addHandler(file_handler)

    # ── Silence noisy third-party loggers ─────────────────────────────────────
    # Only clamp to WARNING when the effective level is finer than WARNING so
    # that DEBUG mode still captures our own app logs while filtering library noise.
    if level < logging.WARNING:
        for name in _NOISY_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)

    # ── First entry ───────────────────────────────────────────────────────────
    logging.getLogger(__name__).info(
        "Logging started — level=%s  file=%s", level_name, log_file
    )


def get_log_file() -> Path:
    """Return the path of the active log file (whether it exists yet or not)."""
    return get_app_data_dir() / "logs" / "uacragent.log"


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
        _atomic_write_text(
            _CONFIG_FILE,
            json.dumps(cfg, indent=2, ensure_ascii=False),
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
    ``language`` ("auto" | "en" | "zh_CN").  When no preference has been saved
    yet, the fallback is English (``"en"``).
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


def get_privacy_accepted() -> bool:
    """Return True if the user has accepted the privacy notice."""
    return bool(_load_config().get("privacy_notice_accepted", False))


def set_privacy_accepted(accepted: bool) -> None:
    """Persist the user's privacy notice acceptance to ``~/.uacragent/config.json``."""
    cfg = _load_config()
    cfg["privacy_notice_accepted"] = bool(accepted)
    _save_config(cfg)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Write *text* to *path* atomically using a sibling temp file + os.replace().

    ``os.replace()`` is atomic on POSIX and effectively atomic on Windows (same
    volume, same directory).  A process crash during the write leaves at most a
    stale ``.tmp`` file — the original *path* is never partially written.
    """
    import os as _os
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(text, encoding=encoding)
        _os.replace(tmp, path)
    except Exception:
        # Clean up the temp file on failure so it doesn't litter the folder.
        try:
            tmp.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        raise


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
    # A dangling message (odd length) indicates a serialisation bug.
    # We keep ALL messages: the dangling tail will be handled by
    # _smart_trim_history (which already guards against odd-length lists)
    # and will be re-persisted correctly on the next save.  Silently dropping
    # the message caused permanent data loss on the next save() call.
    if len(msgs) % 2 != 0:
        logger.error(
            "Deserialised chat history has odd number of messages (%d); "
            "this indicates a prior serialisation bug.  The dangling message "
            "is preserved in memory — it will be corrected on the next save.",
            len(msgs),
        )
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
        _atomic_write_text(
            _get_index_file(),
            json.dumps(records, indent=2, ensure_ascii=False),
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
        "chat_history": _serialise_history(session.chat_history.snapshot()),
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
        _atomic_write_text(
            session_file,
            json.dumps(payload, indent=2, ensure_ascii=False),
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

    The workspace folder itself is removed only when **both** conditions hold:

    1. It resolves under the managed app-data directory (``get_app_data_dir()``),
       meaning it was auto-created by the agent, not chosen explicitly by the
       user.
    2. It is effectively empty after the bundle is removed — "effectively empty"
       means no items remain other than OS-generated metadata files such as
       ``.DS_Store`` and ``Thumbs.db``, which are invisible to the user and safe
       to delete together with the parent folder.

    User-chosen workspace folders (``workspace_folder`` set to an external path)
    are never auto-deleted, even when they appear empty.
    """
    import shutil
    from uacragent.infra.workspace import AGENT_SUBDIR

    agent_dir = workspace / AGENT_SUBDIR
    try:
        if agent_dir.is_dir():
            shutil.rmtree(agent_dir)
    except Exception as exc:
        logger.warning("Could not remove agent dir %s: %s", agent_dir, exc)

    # Remove the workspace folder itself only when it is both effectively
    # empty AND was auto-created by the agent (i.e. it lives inside the
    # managed app-data directory tree).  User-chosen workspace folders that
    # happen to contain only OS metadata files must never be silently deleted
    # — the user picked that location and may rely on it for other purposes.
    #
    # "Effectively empty" = only OS-generated metadata files remain
    # (.DS_Store, Thumbs.db, etc.), which are invisible to the user and safe
    # to remove together with the parent folder.
    _OS_METADATA: frozenset[str] = frozenset({
        ".DS_Store", ".localized", "Thumbs.db", "desktop.ini", ".Spotlight-V100",
    })
    try:
        # Only auto-delete when workspace is under the managed app-data dir.
        # resolve() collapses symlinks and ".." components so the comparison
        # is reliable even when the paths were constructed differently.
        _managed_root = get_app_data_dir().resolve()
        _workspace_resolved = workspace.resolve()
        _is_managed = _workspace_resolved.is_relative_to(_managed_root)

        if _is_managed and workspace.exists():
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
    if not session.workspace_id:
        raise ValueError(
            "Cannot resolve workspace for session with no workspace_id and no "
            "workspace_folder.  Every AgentSession must have a non-empty "
            "workspace_id (normally set by AgentSession.__post_init__)."
        )
    return (get_app_data_dir() / "sessions" / session.workspace_id).resolve()
