from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

try:
    from langchain_chroma import Chroma  # type: ignore
except Exception:  # noqa: BLE001
    from langchain_community.vectorstores import Chroma

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.vectorstores import VectorStore

from uacragent.domain.types import DocumentType
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


# ---------------------------------------------------------------------------
# File-set manifest
# ---------------------------------------------------------------------------
# We cannot link individual Chroma records back to the source file that
# produced them (chunk IDs are content hashes; source paths in metadata point
# to workspace copies, not the original files).  Instead we track the *set*
# of files that were present during the last successful indexing run in a
# small JSON manifest.  On each new indexing run we compare the current file
# set against the manifest:
#
#   • If a file was removed  → wipe Chroma entirely and rebuild from scratch.
#     This is the only correct action because we cannot surgically delete the
#     chunks that belonged to the removed file.
#
#   • If files were only added or unchanged → keep the existing Chroma data
#     and only embed the new chunks (content-hash dedup as before).
# ---------------------------------------------------------------------------

_MANIFEST_FILENAME = "indexed_files.json"


def _manifest_path(workspace_paths: WorkspacePaths) -> Path:
    return Path(workspace_paths.agent_dir) / _MANIFEST_FILENAME


def _load_manifest(workspace_paths: WorkspacePaths) -> set[tuple[str, str]]:
    """Return the set of ``(doc_type_value, file_path)`` pairs from the last run."""
    mp = _manifest_path(workspace_paths)
    if not mp.exists():
        return set()
    try:
        data = json.loads(mp.read_text(encoding="utf-8"))
        return {(f["doc_type"], f["path"]) for f in data.get("files", [])}
    except Exception:
        return set()


def _save_manifest(
    workspace_paths: WorkspacePaths,
    classified_files: dict[DocumentType, list[str]],
) -> None:
    """Persist the current file set so the next run can detect removals."""
    mp = _manifest_path(workspace_paths)
    files = [
        {"doc_type": dt.value, "path": p}
        for dt, paths in classified_files.items()
        for p in paths
    ]
    try:
        mp.write_text(
            json.dumps({"files": files}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass  # non-fatal; worst case we rebuild unnecessarily next time


def _files_were_removed(
    workspace_paths: WorkspacePaths,
    classified_files: dict[DocumentType, list[str]],
) -> bool:
    """Return True if any file present in the last manifest is absent now.

    A missing manifest (first run) is treated as "no removals" — there is
    nothing to purge yet.
    """
    prev = _load_manifest(workspace_paths)
    if not prev:
        return False  # first indexing run; Chroma is empty anyway
    curr = {(dt.value, p) for dt, paths in classified_files.items() for p in paths}
    return bool(prev - curr)  # files in prev that are no longer in curr


# ---------------------------------------------------------------------------
# Chunk helpers
# ---------------------------------------------------------------------------

def _chunk_id(doc: Document) -> str:
    return hashlib.sha256(doc.page_content.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_or_create_vectorstore(
    chunks: list[Document],
    settings: Settings,
    workspace_paths: WorkspacePaths,
    classified_files: dict[DocumentType, list[str]] | None = None,
) -> VectorStore:
    """Build or update the Chroma vector store for the current session.

    Removal-aware rebuild
    ---------------------
    When *classified_files* is supplied, the function checks whether any file
    present during the previous indexing run has since been removed.  If so,
    the Chroma directory is wiped and rebuilt from the current chunks — this
    is the only way to guarantee stale chunks are gone, because there is no
    reliable mapping from a Chroma record back to its originating file.

    If no files were removed (only additions or no change), the existing DB is
    kept and only genuinely new chunks (by content hash) are added.

    After a successful update the current file set is written to a manifest
    (``indexed_files.json`` in the agent dir) so the next run can detect
    removals.
    """
    embeddings = _build_embeddings(settings)
    chroma_dir = Path(workspace_paths.chroma)

    # ── Removal check: wipe and rebuild if files were removed ─────────
    if classified_files is not None and _files_were_removed(workspace_paths, classified_files):
        if chroma_dir.exists():
            shutil.rmtree(chroma_dir)

    chroma_dir.mkdir(parents=True, exist_ok=True)

    db = Chroma(
        persist_directory=str(chroma_dir),
        embedding_function=embeddings,
    )

    # ── Add only new chunks (content-hash dedup) ──────────────────────
    if chunks:
        ids = [_chunk_id(c) for c in chunks]
        existing = db.get(ids=ids)
        existing_ids = set(existing["ids"]) if existing and existing.get("ids") else set()
        new_chunks = [c for c, cid in zip(chunks, ids) if cid not in existing_ids]
        new_ids = [cid for cid in ids if cid not in existing_ids]
        if new_chunks:
            db.add_documents(new_chunks, ids=new_ids)

    # ── Persist manifest so the next run can detect removals ──────────
    if classified_files is not None:
        _save_manifest(workspace_paths, classified_files)

    return db


def build_retriever(vectorstore: VectorStore, settings: Settings) -> BaseRetriever:
    return vectorstore.as_retriever(search_kwargs={"k": settings.retriever_k})
