"""Tests for infra/auth.py and domain/providers.py."""
from __future__ import annotations

import pytest

from uacragent.domain.errors import ConfigurationError
from uacragent.domain.providers import (
    PROVIDERS,
    PROVIDER_IDS,
    ProviderConfig,
    default_model_for,
    env_var_for,
    get_provider,
    models_for,
)
from uacragent.infra.auth import require_api_key
from uacragent.infra.settings import Settings


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

class TestProviderRegistry:
    def test_all_three_providers_present(self):
        for pid in ("gemini", "openai", "deepseek"):
            assert pid in PROVIDERS

    def test_provider_ids_order(self):
        assert PROVIDER_IDS[0] == "gemini"
        assert "openai" in PROVIDER_IDS
        assert "deepseek" in PROVIDER_IDS

    def test_every_provider_has_required_fields(self):
        for pid, cfg in PROVIDERS.items():
            assert cfg.id == pid
            assert cfg.display_name
            assert cfg.settings_attr
            assert cfg.env_var
            assert len(cfg.models) >= 1
            assert cfg.default_model in cfg.models

    def test_get_provider_known(self):
        cfg = get_provider("gemini")
        assert cfg.id == "gemini"

    def test_get_provider_unknown_falls_back_to_gemini(self):
        cfg = get_provider("nonexistent_provider")
        assert cfg.id == "gemini"

    def test_get_provider_empty_falls_back_to_gemini(self):
        cfg = get_provider("")
        assert cfg.id == "gemini"

    def test_env_var_for_known(self):
        assert env_var_for("gemini") == "GOOGLE_API_KEY"
        assert env_var_for("openai") == "OPENAI_API_KEY"
        assert env_var_for("deepseek") == "DEEPSEEK_API_KEY"

    def test_models_for_returns_list(self):
        models = models_for("gemini")
        assert isinstance(models, list)
        assert len(models) >= 1

    def test_default_model_for_all_providers(self):
        for pid in PROVIDER_IDS:
            dm = default_model_for(pid)
            assert dm in models_for(pid)

    def test_deepseek_has_base_url(self):
        cfg = get_provider("deepseek")
        assert cfg.base_url is not None
        assert "deepseek" in cfg.base_url.lower()

    def test_gemini_supports_search_and_files(self):
        cfg = get_provider("gemini")
        assert cfg.supports_search is True
        assert cfg.supports_files is True

    def test_deepseek_does_not_support_search(self):
        cfg = get_provider("deepseek")
        assert cfg.supports_search is False

    def test_provider_configs_are_frozen(self):
        cfg = get_provider("gemini")
        with pytest.raises(Exception):
            cfg.id = "evil"  # type: ignore[misc]

    def test_privacy_policy_urls_non_empty(self):
        for cfg in PROVIDERS.values():
            assert cfg.privacy_policy_url, f"{cfg.id} has no privacy_policy_url"


# ---------------------------------------------------------------------------
# require_api_key
# ---------------------------------------------------------------------------

class TestRequireApiKey:
    def test_raises_when_google_key_missing(self):
        s = Settings(google_api_key="")
        with pytest.raises(ConfigurationError, match="GOOGLE_API_KEY"):
            require_api_key(s, "gemini")

    def test_passes_when_google_key_present(self):
        s = Settings(google_api_key="real-key")
        require_api_key(s, "gemini")  # must not raise

    def test_raises_when_openai_key_missing(self):
        s = Settings(openai_api_key="")
        with pytest.raises(ConfigurationError, match="OPENAI_API_KEY"):
            require_api_key(s, "openai")

    def test_raises_when_deepseek_key_missing(self):
        s = Settings(deepseek_api_key="")
        with pytest.raises(ConfigurationError, match="DEEPSEEK_API_KEY"):
            require_api_key(s, "deepseek")

    def test_defaults_to_settings_llm_provider(self):
        s = Settings(llm_provider="gemini", google_api_key="")
        with pytest.raises(ConfigurationError):
            require_api_key(s)  # no explicit provider — should use settings.llm_provider

    def test_unknown_provider_falls_back_gracefully(self):
        """Unknown provider resolves to gemini; if gemini key missing → raises."""
        s = Settings(google_api_key="")
        with pytest.raises(ConfigurationError):
            require_api_key(s, "unknown_provider_xyz")
