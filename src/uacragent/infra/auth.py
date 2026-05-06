from __future__ import annotations

from uacragent.domain.errors import ConfigurationError
from uacragent.infra.settings import Settings

_PROVIDER_KEY_MAP = {
    "gemini":   ("google_api_key",   "GOOGLE_API_KEY"),
    "openai":   ("openai_api_key",   "OPENAI_API_KEY"),
    "deepseek": ("deepseek_api_key", "DEEPSEEK_API_KEY"),
}


def require_api_key(settings: Settings, provider: str | None = None) -> None:
    """Raise ConfigurationError if the required API key for *provider* is missing.

    Falls back to ``settings.llm_provider`` when *provider* is not given.
    """
    p = (provider or settings.llm_provider or "gemini").lower()
    attr, env_var = _PROVIDER_KEY_MAP.get(p, ("google_api_key", "GOOGLE_API_KEY"))
    if not getattr(settings, attr, ""):
        raise ConfigurationError(
            f"Missing {env_var} for provider '{p}'. "
            f"Set it in your .env file or enter it in ⚙ Settings."
        )


# Keep the old name as an alias so existing call-sites don't break immediately.
def require_google_api_key(settings: Settings) -> None:
    require_api_key(settings, provider="gemini")
