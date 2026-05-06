from __future__ import annotations

import random
import time
from typing import Any, Callable

from uacragent.domain.errors import LLMError
from uacragent.infra.auth import require_api_key
from uacragent.infra.settings import Settings

_RETRYABLE_MARKERS = (
    "503", "429",
    "resource exhausted", "service unavailable",
    "quota", "overloaded", "rate limit",
)

_DEEPSEEK_BASE_URL = "https://api.deepseek.com"


def _build_chat_model(settings: Settings) -> Any:
    """Instantiate the appropriate LangChain chat model for the configured provider."""
    provider = (settings.llm_provider or "gemini").lower()
    model = settings.llm_model

    if provider == "gemini":
        require_api_key(settings, "gemini")
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model, temperature=0)

    if provider == "openai":
        require_api_key(settings, "openai")
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            api_key=settings.openai_api_key,  # type: ignore[arg-type]
            temperature=0,
        )

    if provider == "deepseek":
        require_api_key(settings, "deepseek")
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            api_key=settings.deepseek_api_key,  # type: ignore[arg-type]
            base_url=_DEEPSEEK_BASE_URL,
            temperature=0,
        )

    raise LLMError(f"Unknown LLM provider: '{provider}'. "
                   "Choose from: gemini, openai, deepseek.")


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.llm = _build_chat_model(settings)
        self._max_retries: int = settings.llm_max_retries
        self._base_delay: float = settings.llm_retry_base_delay

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
                    f"LLM request failed: {exc}"
                ) from exc
        raise LLMError("LLM request failed after all retries.")  # pragma: no cover

    def invoke(self, prompt: Any) -> Any:
        return self._call_with_retry(self.llm.invoke, prompt)

    def generate_structured(self, output_model: type, prompt: Any) -> Any:
        structured_llm = self.llm.with_structured_output(output_model)
        return self._call_with_retry(structured_llm.invoke, prompt)
