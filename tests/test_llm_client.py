"""Tests for infra/llm.py — secret scrubbing, retry logic, factory registry."""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch, call

import pytest

from uacragent.domain.errors import LLMError
from uacragent.infra.settings import Settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_settings(**kwargs) -> Settings:
    defaults = dict(
        llm_provider="gemini",
        google_api_key="test-key-abc123",
        llm_max_retries=2,
        llm_retry_base_delay=0.01,  # tiny for tests
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def _make_client(**kwargs):
    """Return an LLMClient with the underlying LLM mocked out."""
    from uacragent.infra.llm import LLMClient
    settings = _fake_settings(**kwargs)
    with patch("uacragent.infra.llm._build_chat_model") as mock_build:
        mock_build.return_value = MagicMock()
        client = LLMClient(settings)
    return client


# ---------------------------------------------------------------------------
# _scrub — API key redaction
# ---------------------------------------------------------------------------

class TestScrub:
    def test_scrubs_known_secret(self):
        client = _make_client(google_api_key="my-secret-key-xyz")
        # Manually inject the secret to test scrubbing
        client._secrets = ("my-secret-key-xyz",)
        result = client._scrub("Error: invalid key my-secret-key-xyz detected")
        assert "my-secret-key-xyz" not in result
        assert "<REDACTED>" in result

    def test_empty_text_unchanged(self):
        client = _make_client()
        assert client._scrub("") == ""

    def test_text_without_secret_unchanged(self):
        client = _make_client(google_api_key="secret123")
        client._secrets = ("secret123",)
        assert client._scrub("no secret here") == "no secret here"

    def test_multiple_occurrences_all_redacted(self):
        client = _make_client()
        client._secrets = ("abc",)
        result = client._scrub("abc and abc again")
        assert "abc" not in result
        assert result.count("<REDACTED>") == 2


# ---------------------------------------------------------------------------
# _call_with_retry
# ---------------------------------------------------------------------------

class TestCallWithRetry:
    def test_success_on_first_attempt(self):
        client = _make_client()
        mock_fn = MagicMock(return_value="ok")
        result = client._call_with_retry(mock_fn)
        assert result == "ok"
        mock_fn.assert_called_once()

    def test_retries_on_429(self):
        client = _make_client(llm_max_retries=2, llm_retry_base_delay=0.001)
        calls = [0]

        def fn():
            calls[0] += 1
            if calls[0] < 3:
                raise Exception("429 rate limit")
            return "success"

        result = client._call_with_retry(fn)
        assert result == "success"
        assert calls[0] == 3

    def test_non_retryable_error_raised_immediately(self):
        client = _make_client(llm_max_retries=3, llm_retry_base_delay=0.001)
        calls = [0]

        def fn():
            calls[0] += 1
            # Important: message must NOT contain any _RETRYABLE_MARKERS keywords
            # ("503", "429", "resource exhausted", "service unavailable",
            # "quota", "overloaded", "rate limit").
            raise ValueError("invalid API key format")

        with pytest.raises(LLMError):
            client._call_with_retry(fn)
        assert calls[0] == 1  # no retries for non-retryable errors

    def test_exceeds_max_retries_raises_llm_error(self):
        client = _make_client(llm_max_retries=2, llm_retry_base_delay=0.001)

        def fn():
            raise Exception("503 service unavailable")

        with pytest.raises(LLMError):
            client._call_with_retry(fn)

    def test_error_message_has_secret_scrubbed(self):
        client = _make_client(google_api_key="topsecret")
        client._secrets = ("topsecret",)

        def fn():
            raise Exception("Unauthorised: topsecret is invalid")

        with pytest.raises(LLMError) as exc_info:
            client._call_with_retry(fn)
        assert "topsecret" not in str(exc_info.value)
        assert "<REDACTED>" in str(exc_info.value)


# ---------------------------------------------------------------------------
# stream_invoke cancellation
# ---------------------------------------------------------------------------

class TestStreamInvoke:
    def test_returns_none_when_cancel_set_before_call(self):
        client = _make_client()
        cancel = threading.Event()
        cancel.set()

        # Even if stream yields chunks, cancel_event is checked first
        client.llm.stream.return_value = iter(["chunk1", "chunk2"])
        result = client.stream_invoke("prompt", cancel_event=cancel)
        assert result is None

    def test_returns_none_when_no_chunks(self):
        client = _make_client()
        cancel = threading.Event()
        client.llm.stream.return_value = iter([])
        result = client.stream_invoke("prompt", cancel_event=cancel)
        assert result is None

    def test_falls_back_to_invoke_when_no_cancel_event(self):
        client = _make_client()
        client.llm.invoke.return_value = "response"
        result = client.stream_invoke("prompt", cancel_event=None)
        client.llm.invoke.assert_called_once()


# ---------------------------------------------------------------------------
# Provider registry integrity (import-time assertion)
# ---------------------------------------------------------------------------

def test_all_providers_have_factory():
    """The module-level assertion catches missing factories at import time."""
    from uacragent.infra import llm as llm_mod
    from uacragent.domain.providers import PROVIDERS
    for pid in PROVIDERS:
        assert pid in llm_mod._LANGCHAIN_FACTORIES, f"No factory for '{pid}'"


# ---------------------------------------------------------------------------
# generate_structured_cancellable
# ---------------------------------------------------------------------------

class TestGenerateStructuredCancellable:
    def test_falls_back_to_generate_structured_when_no_cancel(self):
        client = _make_client()
        from pydantic import BaseModel
        class _M(BaseModel):
            value: str

        with patch.object(client, "generate_structured", return_value=_M(value="x")) as mock_gs:
            result = client.generate_structured_cancellable(_M, "prompt", cancel_event=None)
        mock_gs.assert_called_once_with(_M, "prompt")
        assert result.value == "x"

    def test_returns_none_when_already_cancelled(self):
        client = _make_client()
        from pydantic import BaseModel
        class _M(BaseModel):
            value: str

        cancel = threading.Event()
        cancel.set()

        # Patch generate_structured to block so we verify cancel wins
        def _slow_gs(model, prompt):
            time.sleep(5)
            return _M(value="x")

        with patch.object(client, "generate_structured", side_effect=_slow_gs):
            result = client.generate_structured_cancellable(_M, "prompt", cancel_event=cancel)
        assert result is None
