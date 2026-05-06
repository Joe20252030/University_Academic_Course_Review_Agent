from __future__ import annotations

import random
import time
from typing import Any, Callable

from langchain_google_genai import ChatGoogleGenerativeAI

from uacragent.infra.auth import require_google_api_key
from uacragent.domain.errors import LLMError
from uacragent.infra.settings import Settings

# Error substrings that indicate a transient rate-limit / overload condition
_RETRYABLE_MARKERS = (
    "503",
    "429",
    "resource exhausted",
    "service unavailable",
    "quota",
    "overloaded",
    "rate limit",
)


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        require_google_api_key(settings)
        self.llm = ChatGoogleGenerativeAI(model=settings.llm_model, temperature=0)
        self._max_retries: int = settings.llm_max_retries
        self._base_delay: float = settings.llm_retry_base_delay

    # ------------------------------------------------------------------
    # Internal retry helper
    # ------------------------------------------------------------------

    def _call_with_retry(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Call *fn* with exponential-backoff retry on transient API errors."""
        delay = self._base_delay
        for attempt in range(self._max_retries + 1):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                err_lower = str(exc).lower()
                is_retryable = any(m in err_lower for m in _RETRYABLE_MARKERS)
                if is_retryable and attempt < self._max_retries:
                    jitter = random.uniform(0, delay * 0.25)
                    wait = delay + jitter
                    time.sleep(wait)
                    delay = min(delay * 2, 60.0)
                    continue
                raise LLMError(
                    f"LLM request failed (check network / GOOGLE_API_KEY): {exc}"
                ) from exc
        # Should never reach here
        raise LLMError("LLM request failed after all retries.")  # pragma: no cover

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def invoke(self, prompt: Any) -> Any:
        """Invoke the LLM with automatic retry on rate-limit errors."""
        return self._call_with_retry(self.llm.invoke, prompt)

    def generate_structured(self, output_model: type, prompt: Any) -> Any:
        """Invoke the LLM with structured output and automatic retry."""
        structured_llm = self.llm.with_structured_output(output_model)
        return self._call_with_retry(structured_llm.invoke, prompt)
