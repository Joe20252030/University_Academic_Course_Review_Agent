"""Provider registry — single source of truth for all LLM provider metadata.

Adding a new provider requires exactly **one** change: add a new ``ProviderConfig``
entry to ``PROVIDERS`` below.  All consumers (``infra/auth.py``, ``infra/llm.py``,
``ui/desktop/app.py``) derive their data from this registry so there is no need
to touch multiple files or dicts.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderConfig:
    """All metadata the application needs to work with one LLM provider.

    Attributes:
        id:             Internal slug (e.g. ``"gemini"``).  Used as a dict key
                        and matched against ``Settings.llm_provider``.
        display_name:   Human-readable name for UI labels.
        settings_attr:  Name of the API-key attribute on the ``Settings`` model
                        (e.g. ``"google_api_key"``).
        env_var:        Environment variable that holds the API key
                        (e.g. ``"GOOGLE_API_KEY"``).
        models:         Ordered list of available model names; the first entry is
                        the recommended default.
        base_url:       Optional custom API base URL (only needed for DeepSeek-
                        compatible endpoints).
        label_i18n_key: Key in the ``_STRINGS`` i18n dict for the API-key field
                        label shown in the Settings dialog.
    """

    id: str
    display_name: str
    settings_attr: str
    env_var: str
    models: tuple[str, ...]
    base_url: str | None = None
    label_i18n_key: str = ""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

PROVIDERS: dict[str, ProviderConfig] = {
    "gemini": ProviderConfig(
        id="gemini",
        display_name="Gemini (Google)",
        settings_attr="google_api_key",
        env_var="GOOGLE_API_KEY",
        models=(
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
            "gemini-1.5-pro",
            "gemini-1.5-flash",
        ),
        label_i18n_key="api_key_google",
    ),
    "openai": ProviderConfig(
        id="openai",
        display_name="OpenAI",
        settings_attr="openai_api_key",
        env_var="OPENAI_API_KEY",
        models=(
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
            "gpt-3.5-turbo",
        ),
        label_i18n_key="api_key_openai",
    ),
    "deepseek": ProviderConfig(
        id="deepseek",
        display_name="DeepSeek",
        settings_attr="deepseek_api_key",
        env_var="DEEPSEEK_API_KEY",
        models=(
            "deepseek-chat",
            "deepseek-reasoner",
        ),
        base_url="https://api.deepseek.com",
        label_i18n_key="api_key_deepseek",
    ),
}

# Ordered list of provider IDs (preserves insertion order for UI dropdowns).
PROVIDER_IDS: list[str] = list(PROVIDERS)


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def get_provider(provider_id: str) -> ProviderConfig:
    """Return ``ProviderConfig`` for *provider_id*, defaulting to ``"gemini"``.

    Never raises — an unknown/empty provider silently falls back to Gemini so
    the application stays functional even if a session file contains a stale
    provider string.
    """
    return PROVIDERS.get(provider_id or "gemini", PROVIDERS["gemini"])


def env_var_for(provider_id: str) -> str:
    """Return the environment-variable name for *provider_id*'s API key."""
    return get_provider(provider_id).env_var


def models_for(provider_id: str) -> list[str]:
    """Return the list of available model names for *provider_id*."""
    return list(get_provider(provider_id).models)


def default_model_for(provider_id: str) -> str:
    """Return the recommended default model name for *provider_id*."""
    return get_provider(provider_id).models[0]
