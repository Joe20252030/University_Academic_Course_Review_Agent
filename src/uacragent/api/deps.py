"""FastAPI dependency providers.

Design notes
------------
``get_settings()``
    Returns a *fresh* ``Settings`` instance on every call.  ``Settings`` is a
    lightweight pydantic-settings model that reads ``os.environ`` — creating one
    per request costs a handful of dict lookups and is the safest choice because
    it always reflects the actual environment without any invalidation logic.

``get_agent_service()``
    The ``AgentService`` owns the ``AgentPipeline``, which in turn owns the
    ``DocumentLoader`` and ``LLMClient``.  These are stateless (no in-memory
    session state) so sharing a single instance across requests is fine.
    It is re-created via ``invalidate_agent_service()`` whenever ``os.environ``
    is mutated at runtime (e.g., hot-reload tests, integration test fixtures).
"""
from __future__ import annotations

import threading

from uacragent.agent.service import AgentService
from uacragent.infra.settings import Settings


def get_settings() -> Settings:
    """Return a fresh :class:`~uacragent.infra.settings.Settings` instance.

    Always reads from the current ``os.environ`` so there are no stale-cache
    surprises between requests or after environment mutations in tests.
    """
    return Settings()


# ---------------------------------------------------------------------------
# Agent-service singleton with explicit invalidation
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_agent_service: AgentService | None = None


def get_agent_service() -> AgentService:
    """Return the shared :class:`~uacragent.agent.service.AgentService` instance.

    The service is created lazily on the first call and cached for the lifetime
    of the process.  Call :func:`invalidate_agent_service` to force
    re-creation (e.g., after changing environment variables in tests).
    """
    global _agent_service
    if _agent_service is None:
        with _lock:
            if _agent_service is None:          # double-checked locking
                _agent_service = AgentService(settings=get_settings())
    return _agent_service


def invalidate_agent_service() -> None:
    """Discard the cached :class:`~uacragent.agent.service.AgentService`.

    The next call to :func:`get_agent_service` will construct a new instance
    using the current environment.  Use this in tests or after hot-reload.
    """
    global _agent_service
    with _lock:
        _agent_service = None
