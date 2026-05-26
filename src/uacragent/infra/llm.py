from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any

from uacragent.domain.errors import LLMError
from uacragent.domain.providers import PROVIDERS, get_provider
from uacragent.infra.auth import require_api_key
from uacragent.infra.settings import Settings

_RETRYABLE_MARKERS = (
    "503", "429",
    "resource exhausted", "service unavailable",
    "quota", "overloaded", "rate limit",
)


def _build_chat_model(settings: Settings) -> Any:
    """Instantiate the appropriate LangChain chat model for the configured provider.

    Dispatches via the provider registry so adding a new provider only requires
    a new ``ProviderConfig`` entry in ``domain/providers.py`` *and* a new branch
    in the ``_LANGCHAIN_FACTORIES`` dict below (both in a single file).
    """
    provider_id = (settings.llm_provider or "gemini").lower()
    model = settings.llm_model

    factory = _LANGCHAIN_FACTORIES.get(provider_id)
    if factory is None:
        known = ", ".join(PROVIDERS)
        raise LLMError(
            f"Unknown LLM provider: '{provider_id}'. "
            f"Registered providers: {known}."
        )

    require_api_key(settings, provider_id)
    return factory(settings, model)


# ---------------------------------------------------------------------------
# Per-provider LangChain factory functions
# ---------------------------------------------------------------------------
# Each factory receives the full Settings object and the model name string.
# Add a new entry here when adding a new provider to the registry.

def _gemini_factory(settings: Settings, model: str) -> Any:
    from langchain_google_genai import ChatGoogleGenerativeAI
    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=settings.google_api_key,  # type: ignore[arg-type]
        temperature=0,
    )


def _openai_factory(settings: Settings, model: str) -> Any:
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=model,
        api_key=settings.openai_api_key,  # type: ignore[arg-type]
        temperature=0,
    )


def _deepseek_factory(settings: Settings, model: str) -> Any:
    from langchain_openai import ChatOpenAI
    cfg = get_provider("deepseek")
    return ChatOpenAI(
        model=model,
        api_key=settings.deepseek_api_key,  # type: ignore[arg-type]
        base_url=cfg.base_url,
        temperature=0,
    )


_LANGCHAIN_FACTORIES: dict[str, Callable[[Settings, str], Any]] = {
    "gemini":   _gemini_factory,
    "openai":   _openai_factory,
    "deepseek": _deepseek_factory,
}


# ---------------------------------------------------------------------------
# LLMClient
# ---------------------------------------------------------------------------

class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.llm = _build_chat_model(settings)
        self._max_retries: int = settings.llm_max_retries
        self._base_delay: float = settings.llm_retry_base_delay
        # Collect all non-empty key values so we can scrub them from any error
        # message before it leaves this module.  Some LLM providers echo partial
        # or full API keys in HTTP 401/403 bodies; we must never let that reach
        # chat history, log files, or the UI in readable form.
        self._secrets: tuple[str, ...] = tuple(
            getattr(settings, cfg.settings_attr, "") or ""
            for cfg in PROVIDERS.values()
            if getattr(settings, cfg.settings_attr, "")
        )

    def _scrub(self, text: str) -> str:
        """Replace any known secret value in *text* with a fixed placeholder."""
        for secret in self._secrets:
            if secret in text:
                text = text.replace(secret, "<REDACTED>")
        return text

    def _call_with_retry(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        delay = self._base_delay
        for attempt in range(self._max_retries + 1):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                err_lower = str(exc).lower()
                is_retryable = any(m in err_lower for m in _RETRYABLE_MARKERS)
                if is_retryable and attempt < self._max_retries:
                    jitter = random.uniform(0, delay * 0.25)
                    time.sleep(delay + jitter)
                    delay = min(delay * 2, 60.0)
                    continue
                raise LLMError(
                    f"LLM request failed: {self._scrub(str(exc))}"
                ) from exc
        raise LLMError("LLM request failed after all retries.")  # pragma: no cover

    def invoke(self, prompt: Any) -> Any:
        return self._call_with_retry(self.llm.invoke, prompt)

    def invoke_with_search(self, prompt: Any, provider_id: str) -> Any:
        """Invoke with provider-specific web-search grounding.

        Gemini:  ``google_search`` built-in grounding tool.
        OpenAI:  ``web_search_preview`` built-in tool, with an automatic
                 fallback to a search-capable model name when the tool call
                 is rejected (e.g. older langchain-openai that targets the
                 Chat Completions API instead of the Responses API).
        Others:  regular invoke (no search).
        """
        if provider_id == "gemini":
            try:
                llm_s = self.llm.bind_tools([{"google_search": {}}])
                return self._call_with_retry(llm_s.invoke, prompt)
            except Exception:  # noqa: BLE001
                return self.invoke(prompt)

        if provider_id == "openai":
            # Strategy 1: web_search_preview built-in tool (Responses API path,
            # requires langchain-openai ≥ 0.3 compiled against the Responses API).
            try:
                llm_s = self.llm.bind_tools([{"type": "web_search_preview"}])
                return self._call_with_retry(llm_s.invoke, prompt)
            except Exception:  # noqa: BLE001
                pass

            # Strategy 2: swap to the search-capable model variant directly.
            # gpt-4o → gpt-4o-search-preview, gpt-4o-mini → gpt-4o-mini-search-preview.
            try:
                _SEARCH_MODEL_MAP = {
                    "gpt-4o":      "gpt-4o-search-preview",
                    "gpt-4o-mini": "gpt-4o-mini-search-preview",
                }
                current = (
                    getattr(self.llm, "model_name", None)
                    or getattr(self.llm, "model", "")
                )
                search_model = _SEARCH_MODEL_MAP.get(current)
                if search_model:
                    from langchain_openai import ChatOpenAI as _ChatOpenAI
                    _kw: dict = {"model": search_model}
                    # Carry over the API key if it's stored on the existing llm.
                    _key = (
                        getattr(self.llm, "openai_api_key", None)
                        or getattr(self.llm, "api_key", None)
                    )
                    if _key:
                        _kw["openai_api_key"] = _key
                    llm_s = _ChatOpenAI(**_kw)
                    return self._call_with_retry(llm_s.invoke, prompt)
            except Exception:  # noqa: BLE001
                pass

            # Final fallback: regular invoke without search.
            return self.invoke(prompt)

        # All other providers — no search support.
        return self.invoke(prompt)

    def generate_structured(self, output_model: type, prompt: Any) -> Any:
        structured_llm = self.llm.with_structured_output(output_model)
        return self._call_with_retry(structured_llm.invoke, prompt)
