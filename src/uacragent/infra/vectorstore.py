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
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from uacragent.infra.settings import Settings
from uacragent.infra.auth import require_google_api_key
from uacragent.infra.workspace import WorkspacePaths


def _chunk_id(doc: Document) -> str:
    """Deterministic ID derived from page content so duplicates are skipped."""
    return hashlib.sha256(doc.page_content.encode("utf-8")).hexdigest()


def get_or_create_vectorstore(
    chunks: list[Document],
    settings: Settings,
    workspace_paths: WorkspacePaths,
) -> VectorStore:
    """Open an existing persistent Chroma DB if present; otherwise create one.

    Uses content-based IDs to avoid adding duplicate chunks on repeated runs.
    """

    require_google_api_key(settings)

    embeddings = GoogleGenerativeAIEmbeddings(model=settings.embedding_model)

    chroma_dir = Path(workspace_paths.chroma)
    chroma_dir.mkdir(parents=True, exist_ok=True)

    db = Chroma(
        persist_directory=str(chroma_dir),
        embedding_function=embeddings,
    )

    if chunks:
        # Assign deterministic IDs so Chroma skips already-stored chunks.
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
