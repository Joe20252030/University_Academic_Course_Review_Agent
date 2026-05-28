"""Tests for app-managed cache path helpers."""
from __future__ import annotations

import os
from pathlib import Path

from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2

from uacragent.infra import persistence as persistence_mod
from uacragent.infra import vectorstore as vectorstore_mod


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
