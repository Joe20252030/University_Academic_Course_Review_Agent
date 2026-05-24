"""Rate-tier registry — single source of truth for request-frequency presets.

Each tier maps a named API plan category to three concrete pipeline parameters:

* ``request_delay``      — seconds between sequential LLM section calls in
                           ``write_sections_sequential`` (pipeline.py).
* ``max_retries``        — how many times to retry a transient 429 / 503.
* ``retry_base_delay``   — initial back-off in seconds before the first retry
                           (doubles each attempt, capped at 60 s).

Tier thresholds are based on published rate limits of the most common LLM plans
(as of mid-2025):

┌─────────────┬───────────────────────────────────────────────────────────────┐
│ Tier        │ Typical plans                                                  │
├─────────────┼───────────────────────────────────────────────────────────────┤
│ free        │ Gemini Free (15 RPM), most provider trial / free tiers         │
│ standard    │ DeepSeek standard (60 RPM), OpenAI Tier 1 (≈60–100 RPM)       │
│ pro         │ OpenAI Tier 2–3 (≈500 RPM), Gemini Pay-as-you-go (2 000 RPM)  │
│ unlimited   │ OpenAI Tier 4–5, Gemini Enterprise (10 000+ RPM)              │
└─────────────┴───────────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RateTierConfig:
    """All scheduling parameters for one request-frequency tier.

    Attributes:
        id:               Internal slug (e.g. ``"free"``).
        display_name:     Short human-readable label for UI dropdowns.
        request_delay:    Seconds to pause between consecutive LLM calls
                          inside the generation pipeline.
        max_retries:      Maximum retry attempts on transient rate errors.
        retry_base_delay: Initial back-off before the first retry (seconds).
        plans_hint:       One-line note about which provider plans suit this tier.
        hint_i18n_key:    i18n key for the dynamic hint shown below the selector.
    """

    id: str
    display_name: str
    request_delay: float
    max_retries: int
    retry_base_delay: float
    plans_hint: str       # English fallback; real UI uses hint_i18n_key
    hint_i18n_key: str


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
# Insertion order defines the order items appear in the UI combobox.

RATE_TIERS: dict[str, RateTierConfig] = {
    "free": RateTierConfig(
        id="free",
        display_name="Free",
        request_delay=6.0,
        max_retries=3,
        retry_base_delay=15.0,
        plans_hint="Gemini Free (15 RPM), most provider trial / free tiers",
        hint_i18n_key="rate_hint_free",
    ),
    "standard": RateTierConfig(
        id="standard",
        display_name="Standard",
        request_delay=1.5,
        max_retries=2,
        retry_base_delay=8.0,
        plans_hint="DeepSeek (60 RPM), OpenAI Tier 1 (60–100 RPM)",
        hint_i18n_key="rate_hint_standard",
    ),
    "pro": RateTierConfig(
        id="pro",
        display_name="Pro",
        request_delay=0.3,
        max_retries=2,
        retry_base_delay=4.0,
        plans_hint="OpenAI Tier 2–3, Gemini Paid (500–2 000 RPM)",
        hint_i18n_key="rate_hint_pro",
    ),
    "unlimited": RateTierConfig(
        id="unlimited",
        display_name="Unlimited",
        request_delay=0.0,
        max_retries=1,
        retry_base_delay=2.0,
        plans_hint="OpenAI Tier 4–5, Gemini Enterprise (10 000+ RPM)",
        hint_i18n_key="rate_hint_unlimited",
    ),
}

# Ordered list of IDs (preserves insertion order for UI iteration).
RATE_TIER_IDS: list[str] = list(RATE_TIERS)

# Display-name → id (reverse map for combobox selection → internal key).
RATE_TIER_BY_DISPLAY: dict[str, str] = {
    cfg.display_name: cfg.id for cfg in RATE_TIERS.values()
}


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def get_rate_tier(tier_id: str) -> RateTierConfig:
    """Return ``RateTierConfig`` for *tier_id*, falling back to ``"free"``.

    Never raises — an unknown or empty tier_id silently returns the Free tier
    so the application stays functional even when the env value is stale.
    """
    return RATE_TIERS.get(tier_id or "free", RATE_TIERS["free"])


def display_names() -> list[str]:
    """Return tier display names in registry order (for UI combobox values)."""
    return [cfg.display_name for cfg in RATE_TIERS.values()]
