from __future__ import annotations

from langchain_core.language_models import BaseLanguageModel
from langchain_google_genai import ChatGoogleGenerativeAI

from uacragent.infra.auth import require_google_api_key
from uacragent.domain.errors import LLMError
from uacragent.infra.settings import Settings


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        require_google_api_key(settings)
        self.llm = ChatGoogleGenerativeAI(model=settings.llm_model, temperature=0)

    def with_structured_output(self, output_model: type) -> BaseLanguageModel:
        return self.llm.with_structured_output(output_model)

    def invoke(self, prompt) -> object:
        try:
            return self.llm.invoke(prompt)
        except Exception as exc:  # noqa: BLE001
            raise LLMError(
                f"LLM request failed (check network access and GOOGLE_API_KEY): {exc}"
            ) from exc
