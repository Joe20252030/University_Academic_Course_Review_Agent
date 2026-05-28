"""Tests for app-managed cache path helpers."""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2

from uacragent.infra import persistence as persistence_mod
from uacragent.infra import vectorstore as vectorstore_mod
from uacragent.ui.desktop._settings_mixin import SettingsMixin


def test_get_chroma_onnx_model_dir_is_under_app_data(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(persistence_mod, "get_app_data_dir", lambda: tmp_path)

    assert persistence_mod.get_chroma_onnx_model_dir() == (
        tmp_path / "models" / "chroma" / "onnx_models" / "all-MiniLM-L6-v2"
    )


def test_configure_hf_cache_redirects_chroma_onnx_download_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(persistence_mod, "get_app_data_dir", lambda: tmp_path)

    persistence_mod.configure_hf_cache()

    assert persistence_mod.get_hf_cache_dir() == tmp_path / "models"
    assert os.environ["ANONYMIZED_TELEMETRY"] == "FALSE"
    assert ONNXMiniLM_L6_V2.DOWNLOAD_PATH == (
        tmp_path
        / "models"
        / "chroma"
        / "onnx_models"
        / ONNXMiniLM_L6_V2.MODEL_NAME
    )


def test_onnx_model_is_cached_uses_app_managed_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    model_dir = tmp_path / "models" / "chroma" / "onnx_models" / "all-MiniLM-L6-v2"
    model_file = model_dir / "onnx" / "model.onnx"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    model_file.write_bytes(b"x" * 10_485_760)

    monkeypatch.setattr(
        vectorstore_mod,
        "get_chroma_onnx_model_dir",
        lambda model_name="all-MiniLM-L6-v2": model_dir,
    )

    assert vectorstore_mod._onnx_model_is_cached() is True


def test_frozen_build_uses_onnx_cache_for_default_and_hf_cache_for_other_models(
    monkeypatch,
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        vectorstore_mod,
        "_onnx_model_is_cached",
        lambda: True,
    )
    monkeypatch.setattr(
        vectorstore_mod,
        "_hf_model_is_cached",
        lambda model_name: model_name == "all-MiniLM-L12-v2",
    )

    assert SettingsMixin._is_model_cached("all-MiniLM-L6-v2") is True
    assert SettingsMixin._is_model_cached("all-MiniLM-L12-v2") is True
    assert SettingsMixin._is_model_cached("all-mpnet-base-v2") is False


def test_build_chromadb_onnx_embeddings_accepts_plain_python_lists(monkeypatch) -> None:
    monkeypatch.setattr(vectorstore_mod, "_configure_chromadb_onnx_download_path", lambda: Path("/tmp/fake"))
    monkeypatch.setattr(vectorstore_mod, "_onnx_model_is_cached", lambda: True)

    import chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 as onnx_mod

    class _FakeOnnx:
        MODEL_NAME = "all-MiniLM-L6-v2"
        DOWNLOAD_PATH = Path("/tmp/fake")

        def __call__(self, texts):
            return [[0.1, 0.2, 0.3] for _ in texts]

    monkeypatch.setattr(onnx_mod, "ONNXMiniLM_L6_V2", _FakeOnnx)

    emb = vectorstore_mod._build_chromadb_onnx_embeddings()
    assert emb.embed_documents(["a", "b"]) == [[0.1, 0.2, 0.3], [0.1, 0.2, 0.3]]
    assert emb.embed_query("a") == [0.1, 0.2, 0.3]


def test_frozen_non_default_local_model_uses_huggingface_backend(monkeypatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(vectorstore_mod, "_hf_model_is_cached", lambda model_name: True)
    monkeypatch.setattr(
        vectorstore_mod,
        "_build_chromadb_onnx_embeddings",
        lambda progress_cb=None: (_ for _ in ()).throw(AssertionError("ONNX path should not be used")),
    )
    monkeypatch.setattr(vectorstore_mod, "_local_embeddings_cache", {})

    class _FakeHF:
        def __init__(self, model_name: str):
            self.model_name = model_name

        def embed_documents(self, texts):
            return [[1.0] for _ in texts]

        def embed_query(self, text):
            return [1.0]

    monkeypatch.setitem(
        sys.modules,
        "langchain_huggingface",
        types.SimpleNamespace(HuggingFaceEmbeddings=_FakeHF),
    )

    emb = vectorstore_mod._build_local_embeddings("all-MiniLM-L12-v2")
    assert emb.embed_query("x") == [1.0]
