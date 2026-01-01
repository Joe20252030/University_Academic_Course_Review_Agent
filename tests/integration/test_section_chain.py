from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List

import pytest
from langchain_core.documents import Document

from chains import section_chain
from config import Settings
from schemas.plan import SectionSpec


@dataclass
class _DummyLLMResponse:
	content: str


class _DummyLLM:
	def __init__(self, model: str):
		self.model = model
		self.invocations: List[Any] = []

	def invoke(self, messages: Any) -> _DummyLLMResponse:
		self.invocations.append(messages)
		return _DummyLLMResponse(content="## Dummy Section\n\nGenerated content")


class _DummyRetriever:
	def __init__(self, docs: list[Document]):
		self.docs = docs
		self.queries: list[str] = []

	def invoke(self, query: str) -> list[Document]:
		self.queries.append(query)
		return self.docs


def test_write_section_uses_retriever_context_and_returns_llm_content(monkeypatch: pytest.MonkeyPatch) -> None:
	dummy_llm = _DummyLLM(model="ignored")

	def _llm_factory(*args: Any, **kwargs: Any) -> _DummyLLM:
		return dummy_llm

	monkeypatch.setattr(section_chain, "ChatGoogleGenerativeAI", _llm_factory)

	retriever = _DummyRetriever(docs=[Document(page_content="Some context from docs")])
	section = SectionSpec(title="Midterm Review", key_topics=["Topics", "Tips"], importance=4)
	settings = Settings(LLM_MODEL="no-network")

	output = section_chain.write_section(section, retriever, settings)

	assert output.startswith("## Dummy Section")
	assert retriever.queries == ["Midterm Review Topics Tips"]

	# Ensure the constructed prompt contains our retrieved context.
	assert len(dummy_llm.invocations) == 1
	messages = dummy_llm.invocations[0]
	assert any("Some context from docs" in getattr(m, "content", "") for m in messages)

