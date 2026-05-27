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
    # Recommended rate tier for a typical user of this provider.
    # Used to show a "suggested tier" hint in the Settings dialog when the
    # user's current selection differs from the provider's sensible default.
    # Gemini Free is 15 RPM → "free".  OpenAI and DeepSeek require a paid
    # account to obtain an API key → "standard" is the realistic floor.
    default_rate_tier: str = "free"
    supports_search: bool = False   # provider has a built-in web-search API
    supports_files: bool = False    # provider accepts multimodal file attachments


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
            # ── Gemini 3.x ─────────────────────────────────────────────────
            "gemini-3.5-flash",          # ★ recommended — latest fast model
            "gemini-3.1-pro-preview",    # most capable 3.x (preview)
            "gemini-3.1-flash-lite",     # fast & low-cost 3.x
            "gemini-3-flash-preview",    # earlier 3.0 flash (preview)
            # ── Gemini 2.5 ─────────────────────────────────────────────────
            "gemini-2.5-flash",          # stable fast model, free tier
            "gemini-2.5-pro",            # highest capability 2.5
            "gemini-2.5-flash-lite",     # cheapest 2.5
            # ── Gemini 2.0 ─────────────────────────────────────────────────
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            # ── Gemini 1.5 (legacy) ────────────────────────────────────────
            "gemini-1.5-pro",
            "gemini-1.5-flash",
        ),
        label_i18n_key="api_key_google",
        # Gemini Free: 10 RPM (2.5-flash), 5 RPM (2.5-pro, billing required since Apr 2026).
        # Most developers start on the free tier → "free" is the safest initial suggestion.
        # Users who enable billing (Pay-as-you-go Tier 1: 150–300 RPM) should switch to
        # "standard"; Tier 2 ($250+ cumulative, 1 000+ RPM) maps to "pro".
        default_rate_tier="free",
        supports_search=True,
        supports_files=True,
    ),
    "openai": ProviderConfig(
        id="openai",
        display_name="OpenAI",
        settings_attr="openai_api_key",
        env_var="OPENAI_API_KEY",
        models=(
            # ── GPT-5.5 series ─────────────────────────────────────────────
            "gpt-5.5",                     # best overall — complex reasoning & agents
            "gpt-5.5-pro",                 # higher-quality GPT-5.5
            # ── GPT-5.4 series ─────────────────────────────────────────────
            "gpt-5.4",                     # ★ recommended — lower-cost frontier
            "gpt-5.4-pro",                 # higher-quality GPT-5.4
            "gpt-5.4-mini",                # fast, strong coding
            "gpt-5.4-nano",                # cheapest GPT-5.4, high-volume tasks
            # ── GPT-5 series ───────────────────────────────────────────────
            "gpt-5",                       # previous-gen reasoning
            "gpt-5-mini",                  # cost-sensitive / low-latency
            "gpt-5-nano",                  # fastest & cheapest GPT-5
            # ── GPT-4.1 series ─────────────────────────────────────────────
            "gpt-4.1",                     # strong non-reasoning general tasks
            "gpt-4.1-mini",
            "gpt-4.1-nano",
            # ── GPT-4o series ──────────────────────────────────────────────
            "gpt-4o",
            "gpt-4o-mini",
            # ── Search-capable models ───────────────────────────────────────
            "gpt-4o-search-preview",       # built-in web search
            "gpt-4o-mini-search-preview",  # built-in web search (cheaper)
            # ── Reasoning (o-series) ───────────────────────────────────────
            "o4-mini",
            "o3",
            "o3-mini",
            "o1",
        ),
        label_i18n_key="api_key_openai",
        # OpenAI Tier 1 (first paid tier): 500 RPM for GPT-4o / GPT-4.1 / GPT-5.
        # "standard" (0.5 s delay, ~120 RPM effective) gives 4× headroom at Tier 1.
        # Tier 2 (5 000 RPM) → switch to "pro"; Tier 4–5 (10 000–15 000 RPM) → "unlimited".
        default_rate_tier="standard",
        supports_search=True,
        # NOTE: supports_files is a provider-level flag. The search-preview model
        # variants (gpt-4o-search-preview, gpt-4o-mini-search-preview) do NOT
        # accept file/vision inputs — the upload button should be disabled when
        # one of those models is selected, regardless of this flag.
        supports_files=True,
    ),
    "deepseek": ProviderConfig(
        id="deepseek",
        display_name="DeepSeek",
        settings_attr="deepseek_api_key",
        env_var="DEEPSEEK_API_KEY",
        models=(
            # ── DeepSeek V4 (current) ──────────────────────────────────────
            "deepseek-v4-pro",    # ★ recommended — most capable V4
            "deepseek-v4-flash",  # faster, cost-efficient V4
            # ── Legacy aliases (still supported by the API) ────────────────
            "deepseek-chat",      # alias → deepseek-v4-flash (non-thinking)
            "deepseek-reasoner",  # alias → deepseek-v4-flash (thinking mode)
        ),
        base_url="https://api.deepseek.com",
        label_i18n_key="api_key_deepseek",
        # DeepSeek uses dynamic concurrency-based limiting (no fixed RPM table).
        # Practical ceiling is ~300 RPM for standard accounts; heavy paid usage can
        # reach 1 500+ RPM.  "standard" (0.5 s delay) is a safe conservative default.
        default_rate_tier="standard",
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
