from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import pytest
from langchain_core.documents import Document

from config import Settings
from indexing.retriever import build_retriever
from indexing import vectorstore as vectorstore_module


@dataclass
class _DummyRetriever:
	search_kwargs: dict[str, Any]

	def invoke(self, query: str) -> list[Document]:
		return [Document(page_content=f"dummy answer for: {query}")]


class _DummyVectorStore:
	def __init__(self) -> None:
		self.last_search_kwargs: Optional[dict[str, Any]] = None

	def as_retriever(self, search_kwargs: dict[str, Any]) -> _DummyRetriever:
		self.last_search_kwargs = search_kwargs
		return _DummyRetriever(search_kwargs=search_kwargs)


def test_get_or_create_vectorstore_and_build_retriever_offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
	dummy_store = _DummyVectorStore()

	class _DummyEmbeddings:
		def __init__(self, model: str):
			self.model = model

	class _DummyChroma:
		@staticmethod
		def from_documents(*args: Any, **kwargs: Any) -> _DummyVectorStore:
			return dummy_store

	monkeypatch.setattr(vectorstore_module, "GoogleGenerativeAIEmbeddings", _DummyEmbeddings)
	monkeypatch.setattr(vectorstore_module, "Chroma", _DummyChroma)

	settings = Settings(CHROMA_DIR=str(tmp_path / "chroma"), RETRIEVER_K=3)
	chunks = [Document(page_content="chunk 1"), Document(page_content="chunk 2")]

	store = vectorstore_module.get_or_create_vectorstore(chunks, settings)
	retriever = build_retriever(store, settings)

	assert store is dummy_store
	assert getattr(retriever, "search_kwargs") == {"k": 3}

