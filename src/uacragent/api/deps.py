from __future__ import annotations

from functools import lru_cache

from uacragent.agent.service import AgentService
from uacragent.infra.settings import Settings, get_settings as _get_settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return _get_settings()


@lru_cache(maxsize=1)
def get_agent_service() -> AgentService:
    return AgentService(settings=get_settings())
