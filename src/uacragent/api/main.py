from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from uacragent.api.routes import router
from uacragent.domain.errors import LLMError, UACRAgentError
from uacragent.infra.persistence import OS_METADATA_FILENAMES

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Localhost address set — used for bind-host safety check
# ---------------------------------------------------------------------------
_LOCALHOST_ADDRS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost"})

# Default workspace TTL in hours.  Workspaces older than this are deleted by
# the startup sweep and the hourly background task.
_DEFAULT_TTL_HOURS: float = 24.0


def _is_localhost(addr: str) -> bool:
    """Return True when *addr* refers to a loopback address."""
    return addr.strip().lower() in _LOCALHOST_ADDRS


def _cleanup_expired_api_workspaces(ttl_hours: float) -> int:
    """Delete ``api_run/`` workspaces whose last-modified time exceeds *ttl_hours*.

    Only workspaces that carry a valid ``owner.json`` marker are considered for
    cleanup.  This guarantees that any directory placed manually inside
    ``api_run/`` — or one whose ``.uacragent/`` bundle was not created by this
    app — is never silently wiped by the background cleanup task.

    For each eligible expired workspace the function proceeds in two steps:

    1. :func:`~uacragent.infra.persistence.delete_session` removes the
       ``.uacragent/`` bundle via the standard ownership-checked path.
    2. Only when step 1 confirms full deletion (return value is ``None``) is
       the workspace directory itself removed.  If ``delete_session()`` returns
       a warning string (bundle was preserved), the workspace directory is left
       intact as well, matching the intent of the refusal.

    Returns the number of workspaces successfully removed.
    """
    from uacragent.infra.persistence import get_api_run_dir, delete_session  # noqa: PLC0415
    from uacragent.infra.workspace import AGENT_SUBDIR, has_ownership_marker  # noqa: PLC0415

    api_dir = get_api_run_dir()
    if not api_dir.exists():
        return 0

    cutoff = time.time() - ttl_hours * 3600
    deleted = 0

    for ws in api_dir.iterdir():
        if not ws.is_dir():
            continue

        # Only auto-clean workspaces we can confirm were created by UACRAgent.
        # Workspaces without a valid ownership marker are skipped entirely so
        # manually-placed or externally-owned directories are never touched.
        agent_dir = ws / AGENT_SUBDIR
        if not has_ownership_marker(agent_dir):
            continue

        # Use agent_dir mtime rather than the workspace root mtime.
        # The workspace root's mtime only updates when entries are added to /
        # removed from that specific directory.  Since all writes go into
        # ws/.uacragent/ (a subdirectory), ws/ mtime does not change after
        # initial creation.  agent_dir mtime is updated by every save_session()
        # call and reflects actual last-use time.
        try:
            mtime = agent_dir.stat().st_mtime
        except OSError:
            continue
        if mtime >= cutoff:
            continue

        try:
            bundle_warning = delete_session(ws)
            if bundle_warning:
                # delete_session() refused to remove the .uacragent/ bundle.
                # Do NOT remove the workspace folder either — the refusal means
                # something unexpected is inside it.
                _logger.warning(
                    "API workspace cleanup skipping '%s': %s", ws, bundle_warning
                )
                continue

            # Bundle deleted — remove the workspace folder only when it is
            # effectively empty.  Mirrors GUI delete_session() behaviour:
            # unexpected files at the workspace root are preserved, not wiped.
            if ws.exists():
                if ws.is_symlink():
                    _logger.warning(
                        "Refusing to remove api_run workspace '%s': path is "
                        "a symlink. Manual cleanup may be required.", ws,
                    )
                    continue
                remaining = [
                    p for p in ws.iterdir()
                    if p.name not in OS_METADATA_FILENAMES
                ]
                if remaining:
                    _logger.warning(
                        "API workspace '%s' has %d unexpected item(s) after "
                        "bundle removal; leaving folder intact.",
                        ws, len(remaining),
                    )
                    continue   # don't count as fully deleted
                try:
                    shutil.rmtree(ws)
                except Exception as _rm_exc:  # noqa: BLE001
                    _logger.warning(
                        "Could not remove api_run workspace folder '%s': %s",
                        ws, _rm_exc,
                    )
                    continue   # don't count as deleted if rmtree failed
            deleted += 1
        except Exception as exc:    # noqa: BLE001
            _logger.warning("Could not remove expired api_run workspace %s: %s", ws, exc)

    if deleted:
        _logger.info("API workspace cleanup: removed %d expired workspace(s).", deleted)
    return deleted


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Run startup tasks before the server begins accepting requests."""
    # ── Load environment ──────────────────────────────────────────────────────
    # Load cwd/.env so API keys / provider settings are available via os.environ.
    # dotenv is a soft dependency — skip silently if not installed.
    try:
        from dotenv import load_dotenv  # noqa: PLC0415
        load_dotenv()
    except ImportError:
        pass

    # Point local model downloads at app-managed cache folders.
    from uacragent.infra.persistence import configure_hf_cache  # noqa: PLC0415
    configure_hf_cache()

    # Warn about env vars that look like uacragent settings but aren't recognised.
    from uacragent.infra.settings import warn_unrecognised_env_vars  # noqa: PLC0415
    warn_unrecognised_env_vars()

    # ── Security: bind-host + path-restriction check ──────────────────────────
    # If the server is being exposed beyond localhost (indicated by
    # UACRAGENT_BIND_HOST being set to a non-loopback address), the API MUST
    # have UACRAGENT_ALLOWED_BASE_DIR configured.  Without it, any client can
    # read arbitrary files from the host filesystem via the classified_files
    # parameter — a critical path-traversal risk.
    #
    # UACRAGENT_BIND_HOST is set by the operator alongside the uvicorn --host
    # flag to declare intent.  Example safe launch:
    #
    #   UACRAGENT_BIND_HOST=0.0.0.0 \
    #   UACRAGENT_ALLOWED_BASE_DIR=/data/courses \
    #   uvicorn uacragent.api.main:app --host 0.0.0.0
    #
    bind_host = os.environ.get("UACRAGENT_BIND_HOST", "127.0.0.1").strip()
    allowed_base = os.environ.get("UACRAGENT_ALLOWED_BASE_DIR", "").strip()

    if not _is_localhost(bind_host) and not allowed_base:
        raise RuntimeError(
            "SECURITY: UACRAGENT_BIND_HOST is set to a non-localhost address "
            f"('{bind_host}') but UACRAGENT_ALLOWED_BASE_DIR is not configured.\n\n"
            "Without a path restriction, any client reaching this server can read "
            "arbitrary files from the host filesystem.\n\n"
            "Set UACRAGENT_ALLOWED_BASE_DIR to the root directory that API clients "
            "are permitted to access, then restart the server.\n\n"
            "Example:\n"
            "  UACRAGENT_ALLOWED_BASE_DIR=/data/courses \\\n"
            f"  UACRAGENT_BIND_HOST={bind_host} \\\n"
            "  uvicorn uacragent.api.main:app --host " + bind_host
        )

    if not allowed_base:
        _logger.warning(
            "UACRAGENT_ALLOWED_BASE_DIR is not set.  The API accepts any "
            "absolute host file path submitted by clients.  This is safe only "
            "for local-trusted use (localhost only).  Set this variable to "
            "restrict file access if you expose the API beyond localhost."
        )

    # ── Workspace TTL cleanup ─────────────────────────────────────────────────
    # Read TTL from env (default 24 h).  A TTL of 0 disables automatic cleanup.
    try:
        ttl_hours = float(os.environ.get("UACRAGENT_API_WORKSPACE_TTL_HOURS", _DEFAULT_TTL_HOURS))
    except ValueError:
        _logger.warning(
            "Invalid UACRAGENT_API_WORKSPACE_TTL_HOURS value — using default %.0f h.",
            _DEFAULT_TTL_HOURS,
        )
        ttl_hours = _DEFAULT_TTL_HOURS

    if ttl_hours > 0:
        # Run once at startup to clear leftovers from previous server runs.
        try:
            _cleanup_expired_api_workspaces(ttl_hours)
        except Exception as exc:  # noqa: BLE001
            _logger.warning("Startup workspace cleanup failed: %s", exc)

    # ── Background periodic cleanup ───────────────────────────────────────────
    # Runs every hour while the server is up so long-running deployments do not
    # accumulate workspaces between restarts.
    async def _periodic_cleanup() -> None:
        while True:
            await asyncio.sleep(3600)   # 1 hour
            if ttl_hours > 0:
                try:
                    _cleanup_expired_api_workspaces(ttl_hours)
                except Exception as exc:  # noqa: BLE001
                    _logger.warning("Periodic workspace cleanup failed: %s", exc)

    _cleanup_task = asyncio.create_task(_periodic_cleanup())

    yield   # server runs here

    # ── Shutdown ──────────────────────────────────────────────────────────────
    _cleanup_task.cancel()
    try:
        await _cleanup_task
    except asyncio.CancelledError:
        pass


def create_app() -> FastAPI:
    app = FastAPI(title="UACRAgent", lifespan=_lifespan)
    app.include_router(router)

    @app.exception_handler(LLMError)
    async def llm_error_handler(_, exc: LLMError) -> JSONResponse:
        """Map LLM errors to semantically correct HTTP status codes.

        Rate-limit / quota exhaustion → 429 Too Many Requests.
        Service unavailable / overload → 503 Service Unavailable.
        All other LLM errors          → 400 Bad Request.
        """
        msg = str(exc).lower()
        if any(m in msg for m in ("429", "rate limit", "quota", "resource exhausted")):
            status_code = 429
        elif any(m in msg for m in ("503", "service unavailable", "overloaded")):
            status_code = 503
        else:
            status_code = 400
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})

    @app.exception_handler(UACRAgentError)
    async def uacragent_error_handler(_, exc: UACRAgentError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return app


app = create_app()
