"""Tests for domain/rate_tiers.py and Settings._apply_rate_tier."""
from __future__ import annotations

import pytest

from uacragent.domain.rate_tiers import (
    RATE_TIERS,
    RATE_TIER_IDS,
    RATE_TIER_BY_DISPLAY,
    RateTierConfig,
    display_names,
    get_rate_tier,
)
from uacragent.infra.settings import Settings


# ---------------------------------------------------------------------------
# Registry integrity
# ---------------------------------------------------------------------------

def test_all_four_tiers_present():
    for tier_id in ("free", "standard", "pro", "unlimited"):
        assert tier_id in RATE_TIERS


def test_tier_ids_ordered_correctly():
    assert RATE_TIER_IDS == ["free", "standard", "pro", "unlimited"]


def test_rate_tier_config_fields():
    for tier in RATE_TIERS.values():
        assert isinstance(tier, RateTierConfig)
        assert tier.request_delay >= 0.0
        assert tier.max_retries >= 0
        assert tier.retry_base_delay > 0.0
        assert tier.display_name
        assert tier.plans_hint
        assert tier.hint_i18n_key


def test_display_names_returns_all():
    names = display_names()
    assert len(names) == 4
    assert "Free" in names
    assert "Unlimited" in names


def test_rate_tier_by_display_reverse_map():
    for cfg in RATE_TIERS.values():
        assert RATE_TIER_BY_DISPLAY[cfg.display_name] == cfg.id


# ---------------------------------------------------------------------------
# get_rate_tier
# ---------------------------------------------------------------------------

def test_get_rate_tier_known():
    assert get_rate_tier("free") is RATE_TIERS["free"]
    assert get_rate_tier("pro") is RATE_TIERS["pro"]


def test_get_rate_tier_unknown_returns_free():
    result = get_rate_tier("nonexistent_tier")
    assert result is RATE_TIERS["free"]


def test_get_rate_tier_empty_returns_free():
    result = get_rate_tier("")
    assert result is RATE_TIERS["free"]


# ---------------------------------------------------------------------------
# Ordering / sanity: delay should decrease as tier improves
# ---------------------------------------------------------------------------

def test_free_has_highest_request_delay():
    delays = [RATE_TIERS[t].request_delay for t in RATE_TIER_IDS]
    # free > standard > pro > unlimited (non-strict where unlimited = 0.0)
    assert delays[0] > delays[1] > delays[2] >= delays[3]


def test_free_has_most_retries():
    assert RATE_TIERS["free"].max_retries >= RATE_TIERS["pro"].max_retries


# ---------------------------------------------------------------------------
# Settings._apply_rate_tier
# ---------------------------------------------------------------------------

def test_settings_defaults_to_free_tier():
    s = Settings()
    assert s.rate_tier == "free"
    assert s.llm_request_delay == RATE_TIERS["free"].request_delay
    assert s.llm_max_retries == RATE_TIERS["free"].max_retries
    assert s.llm_retry_base_delay == RATE_TIERS["free"].retry_base_delay


def test_settings_applies_standard_tier(monkeypatch):
    monkeypatch.setenv("RATE_TIER", "standard")
    s = Settings()
    assert s.llm_request_delay == RATE_TIERS["standard"].request_delay
    assert s.llm_max_retries == RATE_TIERS["standard"].max_retries


def test_settings_applies_unlimited_tier(monkeypatch):
    monkeypatch.setenv("RATE_TIER", "unlimited")
    s = Settings()
    assert s.llm_request_delay == 0.0


def test_settings_unknown_tier_does_not_crash(monkeypatch):
    monkeypatch.setenv("RATE_TIER", "bogus_tier")
    s = Settings()
    # Unknown tier → pydantic fields keep their pydantic default values
    assert s.rate_tier == "bogus_tier"


def test_settings_api_keys_redacted():
    s = Settings(google_api_key="real-key", openai_api_key="other-key")
    d = s.model_dump()
    assert d["google_api_key"] == "***"
    assert d["openai_api_key"] == "***"


def test_settings_api_keys_empty_redacted_as_empty():
    s = Settings(google_api_key="", openai_api_key="")
    d = s.model_dump()
    assert d["google_api_key"] == ""
    assert d["openai_api_key"] == ""
