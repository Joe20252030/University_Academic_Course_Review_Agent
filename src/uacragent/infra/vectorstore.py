from __future__ import annotations

import hashlib
import json
import logging
import math
import shutil
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from chromadb.config import Settings as ChromaClientSettings
from langchain_chroma import Chroma

from langchain_core.callbacks.manager import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.vectorstores import VectorStore
from pydantic import Field as _PydanticField

from uacragent.domain.types import DocumentType, TaskType
from uacragent.infra.persistence import get_chroma_onnx_model_dir
from uacragent.infra.settings import Settings
from uacragent.infra.workspace import WorkspacePaths


_DEFAULT_LOCAL_MODEL = "all-MiniLM-L6-v2"

_vs_logger = logging.getLogger(__name__)

# Module-level cache for local HuggingFace embedding model instances.
# Loading a sentence-transformers model from disk into RAM is expensive
# (~1–3 s and produces the "Loading weights" progress bar).  Caching the
# live instance here means the cost is paid only once per process, even
# when multiple sessions use the same model.
# Key: model_name string.  Value: HuggingFaceEmbeddings instance.
_local_embeddings_cache: dict[str, Any] = {}
# Protects _local_embeddings_cache against concurrent writes from two
# background-thread indexing operations that start at the same time.
_local_embeddings_lock: threading.Lock = threading.Lock()


def _build_embeddings(
    settings: Settings,
    progress_cb: Callable[[str], None] | None = None,
) -> Any:
    """Return an embedding model based on *settings.embedding_provider*.

    Providers
    ---------
    "gemini"  — Google Generative AI embeddings (needs GOOGLE_API_KEY)
    "openai"  — OpenAI embeddings              (needs OPENAI_API_KEY)
    "local"   — HuggingFace sentence-transformers, runs entirely on device,
                free with no API key required.

    When the cloud provider fails (missing API key, network error, etc.) the
    exception is re-raised.  The caller is responsible for surfacing the error
    to the user.  Use the local provider explicitly when no cloud key is
    available.
    """
    provider = getattr(settings, "embedding_provider", "gemini")

    if provider == "local":
        local_model = getattr(settings, "local_embedding_model", _DEFAULT_LOCAL_MODEL)
        # progress_cb is forwarded to _build_local_embeddings which manages
        # all messaging itself (distinguishes download vs cache hit).
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

    except Exception:
        # Re-raise so the caller can surface a clear error message to the user.
        # The local provider fallback has been removed — use the "local" provider
        # explicitly if no cloud API key is available.
        raise


def _hf_model_is_cached(model_name: str) -> bool:
    """Return True if *model_name* is fully downloaded in the HuggingFace Hub cache.

    Uses the ``HF_HUB_CACHE`` env var set by ``configure_hf_cache()`` so the
    check targets the app-managed models directory (``<app_data_dir>/models/``),
    not the system-wide ``~/.cache/huggingface/hub``.

    The check verifies that actual model weight files exist inside the
    ``snapshots/`` subtree — not just that the model directory was created.
    HuggingFace Hub creates the ``models--…`` folder as soon as a download
    begins, so a directory-existence check alone would incorrectly report the
    model as cached after a failed or partial download.
    """
    import os as _os
    from pathlib import Path as _Path

    cache_root = _os.environ.get("HF_HUB_CACHE") or str(
        _Path.home() / ".cache" / "huggingface" / "hub"
    )
    # HuggingFace Hub stores models as  models--{org}--{name}  directories.
    # Bare names like "all-MiniLM-L6-v2" are served under "sentence-transformers"
    # by sentence_transformers.
    if "/" in model_name:
        org, name = model_name.split("/", 1)
    else:
        org, name = "sentence-transformers", model_name

    snapshots_dir = _Path(cache_root) / f"models--{org}--{name}" / "snapshots"
    if not snapshots_dir.is_dir():
        return False

    # Verify that at least one snapshot revision directory contains a model
    # weight file (pytorch_model.bin, model.safetensors, …).  These files may
    # be symlinks that point back into the sibling ``blobs/`` directory — that
    # is normal HuggingFace Hub cache layout; we accept both regular files and
    # symlinks here.
    # Also handles sharded formats: pytorch_model-00001-of-00002.bin,
    # model-00001-of-00002.safetensors, etc.
    _WEIGHT_NAMES = {"pytorch_model.bin", "model.safetensors", "tf_model.h5"}
    import re as _re
    _SHARD_PATTERN = _re.compile(
        r'^(pytorch_model|model)-\d+-of-\d+\.(bin|safetensors)$'
    )
    for revision_dir in snapshots_dir.iterdir():
        if not revision_dir.is_dir():
            continue
        for entry in revision_dir.iterdir():
            if not (entry.is_file() or entry.is_symlink()):
                continue
            if entry.name in _WEIGHT_NAMES or _SHARD_PATTERN.match(entry.name):
                return True
    return False


def _onnx_model_is_cached() -> bool:
    """Return True if chromadb's ONNX model file is fully extracted on disk.

    ChromaDB's ``ONNXMiniLM_L6_V2`` considers the model ready only when
    ``<cache>/onnx/model.onnx`` exists (it does the same check internally
    before deciding whether to trigger a download).  Checking that specific
    file — and verifying it has a plausible size — avoids false positives from
    an empty directory or a truncated partial download.
    """
    model_file = get_chroma_onnx_model_dir() / "onnx" / "model.onnx"
    # The extracted model.onnx is ~79 MB; treat anything under 10 MB as corrupt.
    _MIN_BYTES = 10_485_760  # 10 MB
    return model_file.is_file() and model_file.stat().st_size >= _MIN_BYTES


def _configure_chromadb_onnx_download_path() -> Path:
    """Redirect Chroma's ONNX embedding download path into the app data dir."""
    from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import (
        ONNXMiniLM_L6_V2,
    )

    cache_dir = get_chroma_onnx_model_dir(ONNXMiniLM_L6_V2.MODEL_NAME)
    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    ONNXMiniLM_L6_V2.DOWNLOAD_PATH = cache_dir
    return cache_dir


def _poll_download_progress(
    blocking_fn: "Callable[[], Any]",
    cache_dir: Path,
    total_bytes: int,
    progress_cb: "Callable[[str], None] | None",
    label: str,
    track_file: "Path | None" = None,
) -> Any:
    """Run *blocking_fn()* while polling download progress to report %.

    Fires *progress_cb* roughly every 1.5 s with a live message such as::

        "Downloading model files… 34% (30/88 MB)"

    *blocking_fn* executes in the **calling** thread (already a background
    worker from the UI's perspective).  A lightweight daemon thread does
    only the size polling so the download itself is never blocked.  The
    polling thread exits cleanly when *blocking_fn* returns or raises.

    Parameters
    ----------
    track_file:
        When set, poll the size of this single file instead of the whole
        *cache_dir* tree.  Use this when the download target is a single
        archive file whose path is known in advance (e.g. the chromadb
        ONNX ``onnx.tar.gz``).  This avoids inflated counts from partially
        extracted siblings and prevents double-counting.

        When *None*, the function sums every **non-symlink** regular file
        under *cache_dir* recursively.  Symlinks are excluded because the
        HuggingFace Hub cache places the same blob once in ``blobs/`` and
        again as a symlink in ``snapshots/<rev>/`` — following symlinks
        would count each model file twice and produce impossible percentages
        such as "175 / 88 MB".
    """
    import threading as _threading

    if not progress_cb:
        return blocking_fn()

    _stop = _threading.Event()

    def _poll() -> None:
        while not _stop.is_set():
            try:
                if track_file is not None:
                    _done = track_file.stat().st_size if track_file.is_file() else 0
                else:
                    # Exclude symlinks — HF Hub mirrors every blob as a symlink
                    # in snapshots/, so following them doubles the apparent size.
                    _done = sum(
                        f.stat().st_size
                        for f in cache_dir.rglob("*")
                        if f.is_file() and not f.is_symlink()
                    )
                _pct = min(99, int(_done * 100 / max(total_bytes, 1)))
                _done_mb  = _done        / 1_048_576
                _total_mb = total_bytes  / 1_048_576
                progress_cb(
                    f"{label}… {_pct}% ({_done_mb:.0f}/{_total_mb:.0f} MB)"
                )
            except Exception:  # noqa: BLE001
                pass
            _stop.wait(1.5)

    _poll_t = _threading.Thread(target=_poll, daemon=True)
    _poll_t.start()
    try:
        return blocking_fn()
    finally:
        _stop.set()
        _poll_t.join(timeout=3.0)


def _is_network_error(exc: BaseException) -> bool:
    """Return True when *exc* looks like a connectivity / download failure.

    Checks the exception type name and message for common network-error
    indicators so callers can raise a user-friendly :class:`ConfigurationError`
    instead of exposing a raw Python traceback.
    """
    _NETWORK_TYPE_NAMES = {
        "ConnectionError", "HTTPError", "URLError", "RequestException",
        "ConnectTimeout", "ReadTimeout", "Timeout",
    }
    _NETWORK_KEYWORDS = (
        "connection", "network", "timeout", "offline",
        "unreachable", "refused", "socket", "nodename",
        "name or service not known", "failed to establish",
    )
    if isinstance(exc, (OSError, TimeoutError)):
        return True
    if type(exc).__name__ in _NETWORK_TYPE_NAMES:
        return True
    _msg = str(exc).lower()
    return any(kw in _msg for kw in _NETWORK_KEYWORDS)


_NETWORK_ERROR_HINT = (
    "Could not download the embedding model — "
    "please check your internet connection and try again.\n\n"
    "If the problem persists you can switch to a cloud embedding provider:\n"
    "  • Open Session Settings  →  Embedding Provider\n"
    "  • Choose  Gemini  or  OpenAI  instead of  Local"
)


def _build_chromadb_onnx_embeddings(
    progress_cb: "Callable[[str], None] | None" = None,
) -> Any:
    """Wrap chromadb's built-in ONNX embedding as a LangChain Embeddings object.

    ChromaDB ships ``all-MiniLM-L6-v2`` in ONNX format and bundles the
    ``onnxruntime`` and ``tokenizers`` runtimes as direct dependencies.
    No PyTorch is needed, making this the reliable path for the frozen .app.

    The ONNX model file (~80 MB) is downloaded on first use into the
    app-managed models tree under ``<app_data_dir>/models/chroma/onnx_models/``.
    This keeps frozen-app local embeddings inside the same visible app data
    folder used by source installs.

    Download progress is reported via *progress_cb* as percentage updates
    (e.g. ``"Downloading embedding model… 45% (36/80 MB)"``).  When the model
    is already cached, a single "Loading from cache" message is emitted instead.

    Implementation note
    -------------------
    ``DefaultEmbeddingFunction.__call__`` creates a fresh ``ONNXMiniLM_L6_V2``
    instance on **every** invocation, which reloads the tokenizer and ONNX
    ``InferenceSession`` from disk on every batch (both are ``@cached_property``
    on the instance, so per-instance not per-class).  This function instead
    creates **one** ``ONNXMiniLM_L6_V2`` instance, forces the download eagerly
    so real progress can be reported, and shares that instance across all
    subsequent ``embed_documents`` / ``embed_query`` calls via the closure.
    """
    from langchain_core.embeddings import Embeddings
    from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2

    _ONNX_CACHE = _configure_chromadb_onnx_download_path()
    # ChromaDB downloads onnx.tar.gz then extracts it.  Track only the archive
    # file while it is downloading so the percentage reflects the download phase
    # (0 → 99 %) rather than a confusing mix of archive + extracted sizes.
    # Measured on disk: onnx.tar.gz = 79 MB.
    _ONNX_ARCHIVE       = _ONNX_CACHE / "onnx.tar.gz"
    _ONNX_ARCHIVE_BYTES = 82_837_504  # 79 MB

    # The model name shown to the user is always "all-MiniLM-L6-v2" — ONNX is
    # the file format the weights are stored in, not a separate product.  Avoid
    # mentioning "ONNX" or "archive" in progress messages so users understand
    # they are downloading the embedding model, not a runtime tool.
    _MODEL_DISPLAY_NAME = "all-MiniLM-L6-v2"

    # ── Create a single ONNXMiniLM_L6_V2 instance ─────────────────────────────
    # Constructing this object imports onnxruntime, tokenizers, and tqdm — all
    # of which are bundled in the frozen .app.  Any ImportError surfaces here
    # (fast-fail) rather than silently at the first embed call.
    # The download is then triggered eagerly via _download_model_if_not_exists()
    # inside the progress-polling wrapper so the user sees real live progress.
    if _onnx_model_is_cached():
        if progress_cb:
            progress_cb(f"Loading embedding model ({_MODEL_DISPLAY_NAME}) from cache…")
        _onnx_instance = ONNXMiniLM_L6_V2()
    else:
        if progress_cb:
            progress_cb(
                f"Downloading embedding model ({_MODEL_DISPLAY_NAME}, ~79 MB) — "
                "first-time setup, this may take a minute…"
            )
        try:
            # Build the instance FIRST so __init__ can validate that onnxruntime
            # and tokenizers are importable before we start polling.
            _onnx_instance = ONNXMiniLM_L6_V2()

            # Now force the download synchronously inside the progress poller.
            # DefaultEmbeddingFunction() was used here before, but it defers the
            # download to its first __call__ — no download happens at construction
            # time, so the progress bar never updated and the actual download
            # would silently block the first indexing batch instead.
            _poll_download_progress(
                blocking_fn=_onnx_instance._download_model_if_not_exists,
                cache_dir=_ONNX_CACHE,
                total_bytes=_ONNX_ARCHIVE_BYTES,
                progress_cb=progress_cb,
                label=f"Downloading {_MODEL_DISPLAY_NAME}",
                track_file=_ONNX_ARCHIVE,  # track archive only, not extracted files
            )
        except Exception as _dl_exc:
            if _is_network_error(_dl_exc):
                from uacragent.domain.errors import ConfigurationError
                raise ConfigurationError(_NETWORK_ERROR_HINT) from _dl_exc
            raise

    if progress_cb:
        progress_cb(f"✓ Embedding model ({_MODEL_DISPLAY_NAME}) ready — indexing documents…")

    # Wrap the shared instance as a LangChain Embeddings object.  All calls
    # share the same _onnx_instance so the tokenizer and InferenceSession are
    # loaded from disk only once (they are @cached_property on the instance).
    class _OnnxWrapper(Embeddings):
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [list(v) for v in _onnx_instance(texts)]

        def embed_query(self, text: str) -> list[float]:
            return list(_onnx_instance([text])[0])

    return _OnnxWrapper()


def _build_local_embeddings(
    model_name: str,
    progress_cb: Callable[[str], None] | None = None,
) -> Any:
    """Load a local sentence-transformers model — free, no API key needed.

    The model is downloaded from HuggingFace Hub on first use and cached
    locally in the app-managed HuggingFace cache directory.

    *progress_cb* is called with status messages so the caller can surface
    them in the UI.

    In the frozen ``.app`` build the sentence-transformers / PyTorch stack is
    replaced by chromadb's built-in ONNX embedding function (same
    ``all-MiniLM-L6-v2`` model, no PyTorch dependency).

    Raises
    ------
    ConfigurationError
        When no local embedding backend can be loaded.
    """
    _PACKAGES = ["sentence-transformers", "langchain-huggingface"]

    import sys as _sys
    import warnings

    # ── Frozen .app fast-path: use chromadb's bundled ONNX embedding ──────────
    # PyTorch's native C extensions often fail to load inside a PyInstaller
    # bundle on macOS even when collect_all("torch") is used, because the
    # dylib dependency chain is not fully resolved at freeze time.
    # ChromaDB's DefaultEmbeddingFunction ships onnxruntime + tokenizers as
    # direct dependencies — both are far more PyInstaller-friendly than torch.
    if getattr(_sys, "frozen", False):
        try:
            return _build_chromadb_onnx_embeddings(progress_cb=progress_cb)
        except Exception as _onnx_exc:
            from uacragent.domain.errors import ConfigurationError
            # ConfigurationError already carries a user-friendly message
            # (e.g. the network-error hint from _build_chromadb_onnx_embeddings).
            # Re-raise it unchanged so the UI shows the specific diagnosis
            # rather than the generic "Local embedding is not available" fallback.
            if isinstance(_onnx_exc, ConfigurationError):
                raise
            raise ConfigurationError(
                "Local embedding is not available in this build.\n\n"
                "Please switch to a cloud embedding provider:\n"
                "  • Open Session Settings  →  Embedding Provider\n"
                "  • Choose  Gemini  or  OpenAI  instead of  Local\n\n"
                "Cloud embedding requires an API key but no extra installation."
            ) from _onnx_exc

    def _missing_local_deps_error(from_exc: Exception | None = None) -> "ConfigurationError":
        """Return the appropriate ConfigurationError for missing local-embedding deps.

        When running from the standalone .app bundle (sys.frozen = True) the user
        cannot run ``pip install`` — the helpful action is to switch to a cloud
        embedding provider instead.  When running from source they get the normal
        pip-install instruction.
        """
        from uacragent.domain.errors import ConfigurationError
        if getattr(_sys, "frozen", False):
            msg = (
                "Local embedding is not available in this build because the "
                "PyTorch runtime could not be loaded.\n\n"
                "Please switch to a cloud embedding provider:\n"
                "  • Open Session Settings  →  Embedding Provider\n"
                "  • Choose  Gemini  or  OpenAI  instead of  Local\n\n"
                "Cloud embedding requires an API key but no extra installation."
            )
        else:
            msg = (
                "Local embedding model requires additional packages that are not "
                "installed.  Please run:\n\n"
                f"    pip install {' '.join(_PACKAGES)}\n\n"
                "Then restart the application."
            )
        return ConfigurationError(msg)

    try:
        from langchain_huggingface import HuggingFaceEmbeddings  # preferred
    except ImportError as _e:
        # langchain-huggingface not installed (or its torch/transformers deps are
        # missing in the frozen bundle); fall back to community shim.
        # Suppress the LangChainDeprecationWarning that the shim emits on
        # import and instantiation — the user cannot act on it and it is
        # noise in the terminal.
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=DeprecationWarning)
                warnings.filterwarnings("ignore", message=".*langchain.huggingface.*")
                from langchain_community.embeddings import HuggingFaceEmbeddings  # type: ignore[no-redef]
        except ImportError as _e2:
            raise _missing_local_deps_error(_e2) from _e2

    # Return the cached instance if this model was already loaded this session.
    # This avoids the ~1–3 s reload cost on every session open within one run.
    # The lock prevents two concurrent indexing threads from both entering the
    # slow HuggingFace load path simultaneously.
    with _local_embeddings_lock:
        _cached_instance = _local_embeddings_cache.get(model_name)
    if _cached_instance is not None:
        _vs_logger.debug("Local embedding model '%s' served from in-memory cache.", model_name)
        return _cached_instance

    try:
        import os as _os

        _cached = _hf_model_is_cached(model_name)

        # Resolve the HF Hub cache directory for this model so the download
        # progress poller knows where to watch for growing files.
        if "/" in model_name:
            _hf_org, _hf_name = model_name.split("/", 1)
        else:
            _hf_org, _hf_name = "sentence-transformers", model_name
        _hf_cache_dir = Path(
            _os.environ.get("HF_HUB_CACHE")
            or str(Path.home() / ".cache" / "huggingface" / "hub")
        ) / f"models--{_hf_org}--{_hf_name}"
        # Measured on disk (blobs only, symlinks excluded):
        #   pytorch_model.bin  ~87 MB  +  vocab / tokenizer / config  ~0.7 MB
        # Total: ~88 MB.  The HF Hub cache also creates symlinks in snapshots/
        # that mirror each blob — those are excluded from both the size estimate
        # and the polling loop to avoid double-counting (which previously caused
        # the display to show impossible values like "175 / 92 MB").
        _HF_TOTAL_BYTES = 92_274_688  # 88 MB (non-symlink blobs only)

        if _cached:
            if progress_cb:
                progress_cb("Loading embedding model from cache…")
        else:
            if progress_cb:
                progress_cb(
                    f"Downloading embedding model files ({model_name}, ~88 MB) — "
                    "first-time setup, this may take a minute…"
                )

        _prev_bars    = _os.environ.get("HF_HUB_DISABLE_PROGRESS_BARS")
        _prev_hf_warn = _os.environ.get("HF_HUB_DISABLE_IMPLICIT_TOKEN")
        # Only suppress the tqdm download bar when the model is already cached —
        # on first use the bar is the only live progress feedback in the terminal.
        if _cached:
            _os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
        _os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
        try:
            def _load_hf() -> Any:
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", category=DeprecationWarning)
                    warnings.filterwarnings("ignore", message=".*huggingface.*")
                    warnings.filterwarnings("ignore", message=".*HF Hub.*")
                    return HuggingFaceEmbeddings(model_name=model_name)

            if _cached:
                instance = _load_hf()
            else:
                # First-time download: poll the cache directory size so the UI
                # can display live percentage progress instead of a static "…".
                instance = _poll_download_progress(
                    blocking_fn=_load_hf,
                    cache_dir=_hf_cache_dir,
                    total_bytes=_HF_TOTAL_BYTES,
                    progress_cb=progress_cb,
                    label="Downloading model files",
                    # track_file=None → sum non-symlink blobs in cache dir
                )
        finally:
            if _prev_bars is None:
                _os.environ.pop("HF_HUB_DISABLE_PROGRESS_BARS", None)
            else:
                _os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = _prev_bars
            if _prev_hf_warn is None:
                _os.environ.pop("HF_HUB_DISABLE_IMPLICIT_TOKEN", None)
            else:
                _os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = _prev_hf_warn

        if progress_cb:
            progress_cb(f"✓ Embedding model ({model_name}) ready — indexing documents…")
        with _local_embeddings_lock:
            _local_embeddings_cache[model_name] = instance
        return instance
    except Exception as exc:
        # ── Network / connectivity failure during download ─────────────────────
        # Surface a user-friendly message instead of a raw Python traceback.
        # There is no automatic fallback provider — the user must either fix
        # their connection or switch to a cloud embedding provider manually.
        if _is_network_error(exc):
            from uacragent.domain.errors import ConfigurationError
            raise ConfigurationError(_NETWORK_ERROR_HINT) from exc
        # ── Missing ML dependencies (no torch / sentence_transformers) ─────────
        # Catches ModuleNotFoundError raised during instantiation when the
        # required ML packages are absent from the environment.
        if (
            "sentence_transformers" in str(exc)
            or "torch" in str(exc)
            or isinstance(exc, ImportError)
        ):
            raise _missing_local_deps_error(exc) from exc
        raise



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

        "local::all-MiniLM-L6-v2"        # source-mode — HuggingFace / PyTorch
        "local_onnx::all-MiniLM-L6-v2"   # frozen .app — chromadb ONNX runtime
        "gemini::models/text-embedding-004"
        "openai::"

    The ``local`` and ``local_onnx`` variants use the same model weights but
    different runtimes (PyTorch vs ONNX).  Although the outputs are expected to
    be numerically close, they are not guaranteed bit-identical, so a distinct
    fingerprint is used to force a safe re-index when switching between source
    mode and the frozen .app.
    """
    import sys as _sys
    provider = getattr(settings, "embedding_provider", "gemini")
    if provider == "local":
        model = getattr(settings, "local_embedding_model", _DEFAULT_LOCAL_MODEL)
        # In the frozen .app the ONNX runtime is used instead of PyTorch.
        # Distinguish the two backends so a session indexed in source mode is
        # safely re-indexed on first open in the frozen app (and vice-versa).
        if getattr(_sys, "frozen", False):
            provider = "local_onnx"
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
        _vs_logger.warning(
            "Manifest file at %s is unreadable or corrupt — treating as empty. "
            "All documents will be re-indexed on the next run.",
            mp, exc_info=True,
        )
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
        import os as _os
        tmp = mp.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        _os.replace(tmp, mp)
    except Exception as exc:  # noqa: BLE001
        try:
            tmp.unlink(missing_ok=True)  # type: ignore[possibly-undefined]
        except Exception:  # noqa: BLE001
            pass
        # Non-fatal but important: a failed manifest write means the next session
        # open cannot detect which files are already indexed, so it will trigger a
        # full re-embedding run (burning API quota) instead of the fast path.
        _vs_logger.warning(
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
    progress_cb: Callable[[str], None] | None = None,
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
        client_settings=ChromaClientSettings(
            anonymized_telemetry=False,
            is_persistent=True,
        ),
    )

    # ── Add only new chunks (content-hash dedup) ──────────────────────
    # Chroma's SQLite backend can time out on very large id lists sent in a
    # single get() call.  Batching keeps each call within a safe range and
    # avoids hitting SQLite's variable-count limit.
    _GET_BATCH_SIZE = 500
    if chunks:
        ids = [_chunk_id(c) for c in chunks]
        existing_ids: set[str] = set()
        for start in range(0, len(ids), _GET_BATCH_SIZE):
            batch = ids[start : start + _GET_BATCH_SIZE]
            result = db.get(ids=batch)
            existing_ids.update(result.get("ids") or [])
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
    weights: dict = _PydanticField(default_factory=dict)  # {doc_type_value: float}

    # model_config replaces the deprecated inner class Config (Pydantic v2 style).
    # arbitrary_types_allowed is required because `vectorstore` is typed as Any
    # but the actual runtime value is a VectorStore (non-Pydantic type).
    model_config = {"arbitrary_types_allowed": True}

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

        # Allocate slots proportionally; ensure each active type gets ≥ 1 slot.
        # math.ceil is used deliberately: it may over-fetch slightly (total could
        # exceed self.k by up to len(active)-1 chunks), but this is intentional —
        # we prefer too many candidates over too few, and the final slice
        # ``results[: self.k]`` trims the merged list back down to exactly k.
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
            except Exception as exc:  # noqa: BLE001
                # Filtering not supported or no matching docs for this type.
                _vs_logger.debug(
                    "Per-type similarity search failed for doc_type=%r: %s",
                    dt_val, exc,
                )
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
        import os as _os
        tmp = mp.with_suffix(".tmp")
        tmp.write_text(json.dumps({"files": []}, indent=2, ensure_ascii=False), encoding="utf-8")
        _os.replace(tmp, mp)
    except Exception:  # noqa: BLE001
        try:
            tmp.unlink(missing_ok=True)  # type: ignore[possibly-undefined]
        except Exception:  # noqa: BLE001
            pass
        # non-fatal; worst case the next run rebuilds unnecessarily


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
    # Check for the specific Chroma SQLite file rather than any directory entry.
    # Using `any(chroma_dir.iterdir())` is unreliable because macOS creates
    # .DS_Store files in directories, which would make an otherwise empty
    # Chroma directory appear non-empty and skip re-indexing incorrectly.
    if not (chroma_dir / "chroma.sqlite3").exists():
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
