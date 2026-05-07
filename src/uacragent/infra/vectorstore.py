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
    """Return an embedding model based on *settings.embedding_provider*.

    Providers
    ---------
    "gemini"  — Google Generative AI embeddings (needs GOOGLE_API_KEY)
    "openai"  — OpenAI embeddings              (needs OPENAI_API_KEY)
    "local"   — HuggingFace sentence-transformers, runs entirely on device,
                free with no API key required.
    """
    from uacragent.domain.errors import ConfigurationError

    provider = getattr(settings, "embedding_provider", "gemini")

    if provider == "local":
        return _build_local_embeddings(
            getattr(settings, "local_embedding_model", "all-MiniLM-L6-v2")
        )

    if provider == "openai":
        if not settings.openai_api_key:
            raise ConfigurationError(
                "OpenAI embeddings require OPENAI_API_KEY. "
                "Enter it in ⚙ Settings → API Key or set OPENAI_API_KEY in .env."
            )
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(api_key=settings.openai_api_key)  # type: ignore[arg-type]

    # Default: "gemini"
    if not settings.google_api_key:
        raise ConfigurationError(
            "Gemini embeddings require GOOGLE_API_KEY. "
            "Enter it in ⚙ Settings → API Key or set GOOGLE_API_KEY in .env."
        )
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
    return GoogleGenerativeAIEmbeddings(model=settings.embedding_model)


def _build_local_embeddings(model_name: str) -> Any:
    """Load a local sentence-transformers model — free, no API key needed.

    The model is downloaded from HuggingFace Hub on first use and cached
    locally in the app-managed HuggingFace cache directory.

    Requires ``sentence-transformers`` (and optionally ``langchain-huggingface``).
    """
    try:
        from langchain_huggingface import HuggingFaceEmbeddings  # preferred
    except ImportError:
        try:
            from langchain_community.embeddings import HuggingFaceEmbeddings  # type: ignore[no-redef]
        except ImportError as exc:
            from uacragent.domain.errors import ConfigurationError
            raise ConfigurationError(
                "Local embeddings require the 'sentence-transformers' package.\n"
                "Install it with:  pip install sentence-transformers langchain-huggingface"
            ) from exc

    return HuggingFaceEmbeddings(model_name=model_name)


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
