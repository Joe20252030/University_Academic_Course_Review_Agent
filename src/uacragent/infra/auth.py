from __future__ import annotations

from uacragent.domain.errors import ConfigurationError
from uacragent.domain.providers import get_provider
from uacragent.infra.settings import Settings


def require_api_key(settings: Settings, provider: str | None = None) -> None:
    """Raise :class:`~uacragent.domain.errors.ConfigurationError` if the
    required API key for *provider* is missing.

    Falls back to ``settings.llm_provider`` when *provider* is not given.
    Uses the provider registry so adding a new provider never requires touching
    this file.
    """
    p = (provider or settings.llm_provider or "gemini").lower()
    cfg = get_provider(p)
    if not getattr(settings, cfg.settings_attr, ""):
        raise ConfigurationError(
            f"Missing {cfg.env_var} for provider '{p}'. "
            f"Set it in your .env file or enter it in ⚙ Settings."
        )
