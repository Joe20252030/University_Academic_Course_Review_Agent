from __future__ import annotations

import hashlib
import json
import math
import shutil
from pathlib import Path
from typing import Any

try:
    from langchain_chroma import Chroma  # type: ignore
except ImportError:
    from langchain_community.vectorstores import Chroma

from langchain_core.callbacks.manager import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.vectorstores import VectorStore

from uacragent.domain.types import DocumentType, TaskType
from uacragent.infra.settings import Settings
from uacragent.infra.workspace import WorkspacePaths


_DEFAULT_LOCAL_MODEL = "all-MiniLM-L6-v2"

import logging as _logging
_vs_logger = _logging.getLogger(__name__)


def _build_embeddings(
    settings: Settings,
    progress_cb: "Callable[[str], None] | None" = None,
) -> Any:
    """Return an embedding model based on *settings.embedding_provider*.

    Providers
    ---------
    "gemini"  — Google Generative AI embeddings (needs GOOGLE_API_KEY)
    "openai"  — OpenAI embeddings              (needs OPENAI_API_KEY)
    "local"   — HuggingFace sentence-transformers, runs entirely on device,
                free with no API key required.

    Fallback policy
    ---------------
    If the selected cloud provider fails (missing API key, network error,
    quota exceeded, etc.) the function automatically falls back to the local
    sentence-transformers model ``all-MiniLM-L6-v2``.  If that model is not
    yet cached it will be downloaded on first use.  The *progress_cb* is called
    with a visible warning message so the caller can surface it in the UI.
    """
    from collections.abc import Callable  # noqa: F401 (used in type hint only)

    provider = getattr(settings, "embedding_provider", "gemini")

    if provider == "local":
        local_model = getattr(settings, "local_embedding_model", _DEFAULT_LOCAL_MODEL)
        if progress_cb:
            progress_cb(f"Loading local embedding model ({local_model})…")
        return _build_local_embeddings(local_model, progress_cb=progress_cb)

    # ── Attempt cloud embeddings; fall back to local on any failure ───────────
    try:
        if provider == "openai":
            if not settings.openai_api_key:
                raise ValueError("OPENAI_API_KEY is not set.")
            from langchain_openai import OpenAIEmbeddings
            return OpenAIEmbeddings(api_key=settings.openai_api_key)  # type: ignore[arg-type]

        # Default: "gemini"
        if not settings.google_api_key:
            raise ValueError("GOOGLE_API_KEY is not set.")
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        return GoogleGenerativeAIEmbeddings(
            model=settings.embedding_model,
            google_api_key=settings.google_api_key,  # type: ignore[arg-type]
        )

    except Exception as exc:  # noqa: BLE001
        _warn = (
            f"⚠️ {provider.title()} embedding provider unavailable "
            f"({type(exc).__name__}: {exc}). "
            f"Falling back to free local model '{_DEFAULT_LOCAL_MODEL}' — "
            f"this will be downloaded if not already cached."
        )
        _vs_logger.warning("%s", _warn)
        if progress_cb:
            progress_cb(_warn)
        return _build_local_embeddings(_DEFAULT_LOCAL_MODEL, progress_cb=progress_cb)


def _build_local_embeddings(
    model_name: str,
    progress_cb: "Callable[[str], None] | None" = None,
) -> Any:
    """Load a local sentence-transformers model — free, no API key needed.

    The model is downloaded from HuggingFace Hub on first use and cached
    locally in the app-managed HuggingFace cache directory.

    If ``sentence-transformers`` or ``langchain-huggingface`` are absent they
    are auto-installed via ``pip`` before the first attempt.  *progress_cb* is
    called with status messages so the caller can surface them in the UI.
    """
    _PACKAGES = ["sentence-transformers", "langchain-huggingface"]

    def _try_load() -> Any:
        """Attempt import + instantiation; raises ImportError on any missing dep.

        Always prefers ``langchain_huggingface`` (no deprecation warning).
        Falls back to the ``langchain_community`` shim only when the preferred
        package is absent, suppressing the LangChainDeprecationWarning that the
        shim emits so it never reaches the user's terminal.
        """
        import warnings

        try:
            from langchain_huggingface import HuggingFaceEmbeddings  # preferred
        except ImportError:
            # langchain-huggingface not installed; fall back to community shim.
            # Suppress the LangChainDeprecationWarning that the shim emits on
            # import and instantiation — the user cannot act on it and it is
            # noise in the terminal.  The auto-install path below will install
            # langchain-huggingface so subsequent runs use the preferred class.
            try:
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", category=DeprecationWarning)
                    warnings.filterwarnings("ignore", message=".*langchain.huggingface.*")
                    from langchain_community.embeddings import HuggingFaceEmbeddings  # type: ignore[no-redef]
            except ImportError as exc:
                raise ImportError("langchain_community missing") from exc

        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=DeprecationWarning)
                return HuggingFaceEmbeddings(model_name=model_name)
        except Exception as exc:
            # Catches ModuleNotFoundError("No module named 'sentence_transformers'")
            # raised during instantiation when the package is not yet installed.
            if "sentence_transformers" in str(exc) or isinstance(exc, ImportError):
                raise ImportError(str(exc)) from exc
            raise

    try:
        return _try_load()
    except ImportError:
        # ── Auto-install the missing packages and retry ───────────────────────
        _info = (
            "📦 Installing required packages for local embedding model "
            f"({', '.join(_PACKAGES)}) — this may take a minute…"
        )
        _vs_logger.info("%s", _info)
        if progress_cb:
            progress_cb(_info)

        import importlib
        import subprocess
        import sys

        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "--quiet"] + _PACKAGES,
            )
        except subprocess.CalledProcessError as pip_exc:
            from uacragent.domain.errors import ConfigurationError
            raise ConfigurationError(
                f"Auto-install of {', '.join(_PACKAGES)} failed.\n"
                f"Please run manually:  pip install {' '.join(_PACKAGES)}"
            ) from pip_exc

        # Force Python's import finder to rescan sys.path so the packages just
        # installed by pip are visible to the current process without a restart.
        importlib.invalidate_caches()

        if progress_cb:
            progress_cb("✅ Packages installed — loading embedding model…")

        return _try_load()



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


def _embedding_fingerprint(settings: Any) -> str:
    """Return a string that uniquely identifies the active embedding configuration.

    Used by the manifest to detect when the embedding provider or model has
    changed between runs — a mismatch means the stored vectors are incompatible
    with the current query embeddings and a full re-index is required.

    This is purely an internal cache-validity tag, not an API credential.
    Format: ``"<provider>::<model>"``

    Examples::

        "local::all-MiniLM-L6-v2"        # free, no API key
        "gemini::models/text-embedding-004"
        "openai::"
    """
    provider = getattr(settings, "embedding_provider", "gemini")
    if provider == "local":
        model = getattr(settings, "local_embedding_model", _DEFAULT_LOCAL_MODEL)
    else:
        # Cloud providers expose their model via embedding_model (Gemini) or
        # use a fixed default (OpenAI).  Store it so a model-name change also
        # triggers re-indexing.
        model = getattr(settings, "embedding_model", "")
    return f"{provider}::{model}"


def _load_manifest(workspace_paths: WorkspacePaths) -> dict:
    """Return the full manifest dict from the last indexing run.

    Keys: ``"files"`` (list of ``{doc_type, path}`` dicts),
    ``"embedding_config"`` (provider::model string).
    Returns an empty dict when the manifest does not exist or is unreadable.
    """
    mp = _manifest_path(workspace_paths)
    if not mp.exists():
        return {}
    try:
        return json.loads(mp.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_manifest(
    workspace_paths: WorkspacePaths,
    classified_files: dict[DocumentType, list[str]],
    settings: Any = None,
) -> None:
    """Persist the current file set and embedding config for the next run."""
    mp = _manifest_path(workspace_paths)
    files = [
        {"doc_type": dt.value, "path": p}
        for dt, paths in classified_files.items()
        for p in paths
    ]
    data: dict = {"files": files}
    if settings is not None:
        data["embedding_config"] = _embedding_fingerprint(settings)
    try:
        mp.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        # Non-fatal but important: a failed manifest write means the next session
        # open cannot detect which files are already indexed, so it will trigger a
        # full re-embedding run (burning API quota) instead of the fast path.
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "Failed to write indexing manifest to %s — next session open will "
            "rebuild the vector store from scratch: %s",
            mp, exc,
        )


def _files_were_removed(
    workspace_paths: WorkspacePaths,
    classified_files: dict[DocumentType, list[str]],
) -> bool:
    """Return True if any file present in the last manifest is absent now.

    A missing manifest (first run) is treated as "no removals" — there is
    nothing to purge yet.
    """
    data = _load_manifest(workspace_paths)
    if not data:
        return False  # first indexing run; Chroma is empty anyway
    prev = {(f["doc_type"], f["path"]) for f in data.get("files", [])}
    if not prev:
        return False
    curr = {(dt.value, p) for dt, paths in classified_files.items() for p in paths}
    return bool(prev - curr)  # files in prev that are no longer in curr


# ---------------------------------------------------------------------------
# Chunk helpers
# ---------------------------------------------------------------------------

def _chunk_id(doc: Document) -> str:
    """Return a stable, unique ID for *doc*.

    The hash includes both the page content *and* the source file path from
    ``doc.metadata`` so that two files with identical content produce distinct
    chunks in the vector store.  Previously only the content was hashed, which
    silently deduplicated identical content from different source files.
    """
    source = doc.metadata.get("source", "")
    payload = f"{source}\x00{doc.page_content}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_or_create_vectorstore(
    chunks: list[Document],
    settings: Settings,
    workspace_paths: WorkspacePaths,
    classified_files: dict[DocumentType, list[str]] | None = None,
    progress_cb: "Callable[[str], None] | None" = None,
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
    embeddings = _build_embeddings(settings, progress_cb=progress_cb)
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
        existing_ids = set(existing.get("ids") or [])
        new_chunks = [c for c, cid in zip(chunks, ids) if cid not in existing_ids]
        new_ids = [cid for cid in ids if cid not in existing_ids]
        if new_chunks:
            db.add_documents(new_chunks, ids=new_ids)

    # ── Persist manifest so the next run can detect removals ──────────
    if classified_files is not None:
        _save_manifest(workspace_paths, classified_files, settings)

    return db


def build_retriever(vectorstore: VectorStore, settings: Settings) -> BaseRetriever:
    return vectorstore.as_retriever(search_kwargs={"k": settings.retriever_k})


# ---------------------------------------------------------------------------
# Weighted retriever
# ---------------------------------------------------------------------------

class WeightedDocTypeRetriever(BaseRetriever):
    """Retriever that proportionally allocates *k* slots to each doc type.

    For each document type present in the session, the number of chunks
    fetched is proportional to that type's weight in the priority matrix.
    Per-type similarity searches are merged and deduplicated so the final
    result contains at most *k* unique chunks.

    Falls back gracefully: if the vector store does not support metadata
    filtering (e.g. an in-memory store in tests), each per-type search
    silently returns an empty list and the caller receives fewer than *k*
    chunks rather than raising an error.

    Attributes
    ----------
    vectorstore:
        The underlying Chroma (or compatible) vector store.
    k:
        Total number of chunks to return.
    weights:
        ``{doc_type_value: relative_weight}`` for the types that are
        actually present in the session.  Only types listed here are
        queried.  Types with weight ``0.0`` are skipped.
    """

    # Pydantic field declarations (compatible with both v1 and v2 base classes
    # used by different LangChain versions).
    vectorstore: Any  # VectorStore — declared as Any to avoid Pydantic issues
    k: int = 8
    weights: dict = {}  # {doc_type_value: float}

    class Config:
        arbitrary_types_allowed = True

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        active = {dt: w for dt, w in self.weights.items() if w > 0.0}
        if not active:
            # No weighted doc types — fall back to unfiltered search
            return self.vectorstore.similarity_search(query, k=self.k)

        total_weight = sum(active.values())

        # Allocate slots proportionally; ensure each active type gets ≥ 1 slot
        allocations: dict[str, int] = {
            dt_val: max(1, math.ceil(self.k * w / total_weight))
            for dt_val, w in active.items()
        }

        seen_hashes: set[str] = set()
        results: list[Document] = []

        for dt_val, k_i in allocations.items():
            try:
                docs = self.vectorstore.similarity_search(
                    query,
                    k=k_i,
                    filter={"doc_type": dt_val},
                )
            except Exception:  # noqa: BLE001
                # Filtering not supported or no matching docs — skip silently
                docs = []

            for doc in docs:
                # Deduplicate by content hash so overlapping results from
                # different per-type searches don't inflate the context
                h = hashlib.sha256(doc.page_content.encode("utf-8")).hexdigest()
                if h not in seen_hashes:
                    seen_hashes.add(h)
                    results.append(doc)

        return results[: self.k]


def build_weighted_retriever(
    vectorstore: VectorStore,
    k: int,
    task_type: TaskType,
    classified_files: dict[DocumentType, list[str]],
) -> BaseRetriever:
    """Return a task-type-aware retriever that weights chunks by doc type.

    When only one doc type is present (or *classified_files* is empty) the
    function falls back to a plain ``similarity_search``-based retriever so
    the caller always receives a valid ``BaseRetriever``.

    Parameters
    ----------
    vectorstore:
        The session's Chroma vector store.
    k:
        Total number of chunks to retrieve per query.
    task_type:
        Determines the weight matrix to use.
    classified_files:
        Maps each :class:`~uacragent.domain.types.DocumentType` to the list
        of file paths present in the session.  Types with an empty list are
        excluded from the weight allocation.
    """
    from uacragent.domain.doc_priorities import get_present_weights

    present_weights = get_present_weights(task_type, classified_files)

    # With only one active doc type weighting adds no value — plain retriever
    if len(present_weights) <= 1:
        return vectorstore.as_retriever(search_kwargs={"k": k})

    return WeightedDocTypeRetriever(
        vectorstore=vectorstore,
        k=k,
        weights=present_weights,
    )


def reset_manifest(workspace_paths: WorkspacePaths) -> None:
    """Overwrite the indexed-files manifest with an empty file set.

    Called when all documents are removed from a session so the next
    indexing run starts from a clean slate rather than comparing against
    stale paths from the previous run.  Safe to call when the manifest
    file does not exist yet.
    """
    mp = _manifest_path(workspace_paths)
    try:
        mp.write_text(
            json.dumps({"files": []}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        pass  # non-fatal; worst case the next run rebuilds unnecessarily


def chroma_is_current(
    workspace_paths: WorkspacePaths,
    classified_files: dict[DocumentType, list[str]],
    settings: Any = None,
) -> bool:
    """Return True when the ChromaDB on disk is up to date with *classified_files*.

    Checks three things:

    1. The Chroma directory exists and is non-empty.
    2. The indexed-files manifest exactly matches the current file set (no
       additions, no removals).
    3. If *settings* is provided, the embedding provider and model recorded in
       the manifest match the current configuration.  A mismatch means the
       stored vectors were built with a different embedding space and the DB
       must be rebuilt.

    A True result means a retriever can be opened from disk without any
    re-embedding work.
    """
    chroma_dir = Path(workspace_paths.chroma)
    if not chroma_dir.exists() or not any(chroma_dir.iterdir()):
        return False
    data = _load_manifest(workspace_paths)
    if not data:
        return False
    prev_files = {(f["doc_type"], f["path"]) for f in data.get("files", [])}
    curr_files = {(dt.value, p) for dt, paths in classified_files.items() for p in paths}
    if prev_files != curr_files:
        return False
    # Check embedding config only when settings are provided and the manifest
    # has a recorded key (old manifests without the key are treated as a miss
    # so they get rebuilt once with the key stored).
    if settings is not None:
        stored_key = data.get("embedding_config")
        if stored_key is None or stored_key != _embedding_fingerprint(settings):
            return False
    return True
