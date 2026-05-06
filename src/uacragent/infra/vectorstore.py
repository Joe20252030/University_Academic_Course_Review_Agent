from __future__ import annotations

import hashlib
from pathlib import Path

try:
    from langchain_chroma import Chroma  # type: ignore
except Exception:  # noqa: BLE001
    from langchain_community.vectorstores import Chroma

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.vectorstores import VectorStore

from uacragent.infra.settings import Settings
from uacragent.infra.workspace import WorkspacePaths


def _build_embeddings(settings: Settings) -> Any:  # type: ignore[name-defined]
    """Return the best available embedding model.

    Priority: Gemini → OpenAI → error.
    This is independent of the LLM provider so users can mix-and-match
    (e.g. OpenAI for generation with Gemini embeddings).
    """
    if settings.google_api_key:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        return GoogleGenerativeAIEmbeddings(model=settings.embedding_model)

    if settings.openai_api_key:
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(
            api_key=settings.openai_api_key,  # type: ignore[arg-type]
        )

    from uacragent.domain.errors import ConfigurationError
    raise ConfigurationError(
        "No API key available for embeddings. "
        "Set GOOGLE_API_KEY or OPENAI_API_KEY in your .env or ⚙ Settings."
    )


# Use Any at module level to avoid the forward-ref issue
from typing import Any  # noqa: E402


def _chunk_id(doc: Document) -> str:
    return hashlib.sha256(doc.page_content.encode("utf-8")).hexdigest()


def get_or_create_vectorstore(
    chunks: list[Document],
    settings: Settings,
    workspace_paths: WorkspacePaths,
) -> VectorStore:
    embeddings = _build_embeddings(settings)

    chroma_dir = Path(workspace_paths.chroma)
    chroma_dir.mkdir(parents=True, exist_ok=True)

    db = Chroma(
        persist_directory=str(chroma_dir),
        embedding_function=embeddings,
    )

    if chunks:
        ids = [_chunk_id(c) for c in chunks]
        existing = db.get(ids=ids)
        existing_ids = set(existing["ids"]) if existing and existing.get("ids") else set()
        new_chunks = [c for c, cid in zip(chunks, ids) if cid not in existing_ids]
        new_ids = [cid for cid in ids if cid not in existing_ids]
        if new_chunks:
            db.add_documents(new_chunks, ids=new_ids)

    return db


def build_retriever(vectorstore: VectorStore, settings: Settings) -> BaseRetriever:
    return vectorstore.as_retriever(search_kwargs={"k": settings.retriever_k})
