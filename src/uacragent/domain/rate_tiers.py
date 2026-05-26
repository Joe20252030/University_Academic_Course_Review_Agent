"""Rate-tier registry — single source of truth for request-frequency presets.

Each tier maps a named API plan category to three concrete pipeline parameters:

* ``request_delay``      — seconds between sequential LLM section calls in
                           ``write_sections_sequential`` (pipeline.py).
* ``max_retries``        — how many times to retry a transient 429 / 503.
* ``retry_base_delay``   — initial back-off in seconds before the first retry
                           (doubles each attempt, capped at 60 s).

Tier thresholds are based on published rate limits of the most common LLM plans
(as of 2026):

┌─────────────┬─────────────────────────────────────────────────────────────────┐
│ Tier        │ Typical plans                                                    │
├─────────────┼─────────────────────────────────────────────────────────────────┤
│ free        │ Gemini Free (10 RPM for 2.5-flash, 5 RPM for 2.5-pro)           │
│ standard    │ OpenAI Tier 1 (500 RPM), DeepSeek (~300 RPM dynamic),           │
│             │ Gemini Pay-as-you-go Tier 1 (150–300 RPM)                       │
│ pro         │ OpenAI Tier 2–3 (5 000–10 000 RPM), Gemini Tier 2 (1 000+ RPM) │
│ unlimited   │ OpenAI Tier 4–5 (10 000–15 000 RPM), Gemini Enterprise (4 000+) │
└─────────────┴─────────────────────────────────────────────────────────────────┘
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
        # 6 s gives ~10 RPM effective — exactly matches Gemini 2.5-flash free limit.
        # Extra retries (4) and a long base back-off (20 s) absorb the frequent
        # 429 storms that free-tier accounts experience during peak hours.
        request_delay=6.0,
        max_retries=4,
        retry_base_delay=20.0,
        plans_hint="Gemini Free (10 RPM for 2.5-flash, 5 RPM for 2.5-pro)",
        hint_i18n_key="rate_hint_free",
    ),
    "standard": RateTierConfig(
        id="standard",
        display_name="Standard",
        # 0.5 s gives ~120 RPM effective — safely under all standard paid limits:
        #   • OpenAI Tier 1: 500 RPM  (0.12 s minimum → 0.5 s = 4× headroom)
        #   • Gemini Pay-as-you-go Tier 1: 150–300 RPM (0.2–0.4 s minimum → safe)
        #   • DeepSeek: ~300 RPM dynamic (concurrency-based; 0.5 s is conservative)
        request_delay=0.5,
        max_retries=3,
        retry_base_delay=8.0,
        plans_hint="OpenAI Tier 1 (500 RPM), Gemini Paid Tier 1 (150–300 RPM), DeepSeek (~300 RPM)",
        hint_i18n_key="rate_hint_standard",
    ),
    "pro": RateTierConfig(
        id="pro",
        display_name="Pro",
        # 0.1 s gives ~600 RPM effective — well within all pro-tier limits:
        #   • OpenAI Tier 2: 5 000 RPM; Tier 3: 10 000 RPM
        #   • Gemini Tier 2: 1 000+ RPM (0.06 s minimum → 0.1 s is safe)
        request_delay=0.1,
        max_retries=2,
        retry_base_delay=3.0,
        plans_hint="OpenAI Tier 2–3 (5 000–10 000 RPM), Gemini Tier 2 (1 000+ RPM)",
        hint_i18n_key="rate_hint_pro",
    ),
    "unlimited": RateTierConfig(
        id="unlimited",
        display_name="Unlimited",
        # No inter-request delay; relies solely on retry back-off for transient errors.
        # Suitable for OpenAI Tier 4–5 (10 000–15 000 RPM) and Gemini Enterprise
        # (4 000+ RPM) where throughput is effectively unconstrained for this app.
        request_delay=0.0,
        max_retries=1,
        retry_base_delay=2.0,
        plans_hint="OpenAI Tier 4–5 (10 000–15 000 RPM), Gemini Enterprise (4 000+ RPM)",
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
