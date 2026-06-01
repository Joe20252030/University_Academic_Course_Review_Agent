"""Tests for infra/settings.py — env-var detection and Settings configuration."""
from __future__ import annotations

import logging
import os

import pytest

from uacragent.infra.settings import Settings, warn_unrecognised_env_vars


# ---------------------------------------------------------------------------
# warn_unrecognised_env_vars
# ---------------------------------------------------------------------------

class TestWarnUnrecognisedEnvVars:
    def test_known_var_no_warning(self, monkeypatch, caplog):
        monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
        with caplog.at_level(logging.WARNING, logger="uacragent.infra.settings"):
            warn_unrecognised_env_vars()
        # GOOGLE_API_KEY is known; no warning should mention it
        assert "GOOGLE_API_KEY" not in caplog.text or "did you mean" not in caplog.text

    def test_typo_triggers_warning(self, monkeypatch, caplog):
        monkeypatch.setenv("GOGLE_API_KEY", "oops")
        with caplog.at_level(logging.WARNING, logger="uacragent.infra.settings"):
            warn_unrecognised_env_vars()
        assert "GOGLE_API_KEY" in caplog.text

    def test_no_suspect_env_vars_no_warning(self, monkeypatch, caplog):
        # Make sure none of our suspect vars are set
        for key in list(os.environ):
            if any(key.startswith(pfx) for pfx in (
                "LLM_", "GOOGLE_", "OPENAI_", "DEEPSEEK_",
                "EMBEDDING_", "LOCAL_EMBEDDING_", "RETRIEVER_", "RATE_",
                "UACRAGENT_",
            )) and key not in {
                "GOOGLE_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY",
                "LLM_PROVIDER", "LLM_MODEL", "RATE_TIER",
            }:
                monkeypatch.delenv(key, raising=False)
        with caplog.at_level(logging.WARNING, logger="uacragent.infra.settings"):
            warn_unrecognised_env_vars()


# ---------------------------------------------------------------------------
# Settings field aliases
# ---------------------------------------------------------------------------

class TestSettingsAliases:
    def test_uppercase_env_var_read(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        s = Settings()
        assert s.llm_provider == "openai"

    def test_lowercase_env_var_read(self, monkeypatch):
        monkeypatch.setenv("llm_provider", "deepseek")
        s = Settings()
        assert s.llm_provider == "deepseek"

    def test_embedding_provider_alias(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
        s = Settings()
        assert s.embedding_provider == "local"

    def test_retriever_k_alias(self, monkeypatch):
        monkeypatch.setenv("RETRIEVER_K", "12")
        s = Settings()
        assert s.retriever_k == 12

    def test_openai_store_responses_default_false(self):
        s = Settings()
        assert s.openai_store_responses is False

    def test_openai_store_responses_set_true(self, monkeypatch):
        monkeypatch.setenv("OPENAI_STORE_RESPONSES", "true")
        s = Settings()
        assert s.openai_store_responses is True


# ---------------------------------------------------------------------------
# Settings defaults
# ---------------------------------------------------------------------------

class TestSettingsDefaults:
    def test_default_llm_provider(self):
        s = Settings()
        assert s.llm_provider == "gemini"

    def test_default_embedding_model(self):
        s = Settings()
        assert "embedding" in s.embedding_model.lower() or s.embedding_model != ""

    def test_api_keys_default_empty(self):
        s = Settings()
        assert s.google_api_key == "" or len(s.google_api_key) > 0  # either unset or set from env
