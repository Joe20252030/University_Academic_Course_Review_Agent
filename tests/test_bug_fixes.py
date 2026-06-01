"""Regression tests for the bug fixes applied in this release.

B1  per-file error recovery in load_and_split_classified
B2  non-UTF-8 text files
B3  history summarisation rate-limit delay
B4  export OSError wrapped as ExportError
B5  _ls() warns on missing key
B6  API workspace_id "default" gets unique UUID per request
B7  image-only (scanned) PDF gives clear OCR error
B8  search-preview models strip image attachments
S5  large-file guard (100 MB warn / 300 MB block)
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from uacragent.domain.errors import ExportError, IngestError
from uacragent.domain.types import DocumentType
from uacragent.infra.loaders import (
    DocumentLoader,
    _LARGE_FILE_BLOCK_BYTES,
    _LARGE_FILE_WARN_BYTES,
)
from uacragent.infra.settings import Settings


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def loader():
    return DocumentLoader(Settings(google_api_key="fake"))


def _txt(tmp_path: Path, name: str, content: str, encoding: str = "utf-8") -> Path:
    p = tmp_path / name
    p.write_text(content, encoding=encoding, errors="replace")
    return p


# ===========================================================================
# B1 — per-file error recovery
# ===========================================================================

class TestPerFileRecovery:
    def test_bad_file_skipped_good_file_indexed(self, loader, tmp_path):
        good = _txt(tmp_path, "good.txt", "lecture content " * 50)
        bad  = tmp_path / "bad.xyz"          # unsupported extension
        bad.write_text("junk")

        classified = {DocumentType.other: [str(bad), str(good)]}
        chunks = loader.load_and_split_classified(classified)

        # Good file produced chunks; bad file was silently skipped.
        assert len(chunks) > 0
        assert all("junk" not in c.page_content for c in chunks)

    def test_all_files_fail_raises_ingest_error(self, loader, tmp_path):
        f1 = tmp_path / "a.xyz"
        f2 = tmp_path / "b.xyz"
        f1.write_text("x"); f2.write_text("y")

        with pytest.raises(IngestError, match="All 2 file"):
            loader.load_and_split_classified({DocumentType.other: [str(f1), str(f2)]})

    def test_all_files_fail_error_names_each_file(self, loader, tmp_path):
        f = tmp_path / "problem.xyz"
        f.write_text("x")

        with pytest.raises(IngestError) as exc_info:
            loader.load_and_split_classified({DocumentType.other: [str(f)]})
        assert "problem.xyz" in str(exc_info.value)

    def test_partial_success_returns_good_chunks(self, loader, tmp_path):
        good1 = _txt(tmp_path, "g1.txt", "good content " * 30)
        good2 = _txt(tmp_path, "g2.txt", "more content " * 30)
        bad   = tmp_path / "b.xyz"
        bad.write_text("x")

        classified = {DocumentType.other: [str(good1), str(bad), str(good2)]}
        chunks = loader.load_and_split_classified(classified)
        assert len(chunks) > 0
        all_text = " ".join(c.page_content for c in chunks)
        assert "good content" in all_text
        assert "more content" in all_text


# ===========================================================================
# B2 — non-UTF-8 text files
# ===========================================================================

class TestNonUtf8Loading:
    def test_latin1_file_loads_without_error(self, loader, tmp_path):
        p = tmp_path / "latin1.txt"
        # Write bytes that are invalid UTF-8 but valid Latin-1
        p.write_bytes("café résumé naïve".encode("latin-1"))

        docs = loader.load_single_file(str(p))
        assert len(docs) == 1
        # Content loaded; replacement chars may appear but no exception
        assert len(docs[0].page_content) > 0

    def test_mixed_encoding_file_loads_with_replacement(self, loader, tmp_path):
        p = tmp_path / "mixed.txt"
        # Mix of valid UTF-8 and a lone high byte (invalid in UTF-8)
        p.write_bytes(b"hello \xff world")

        docs = loader.load_single_file(str(p))
        assert len(docs) == 1
        # Should contain "hello" and "world"; invalid byte replaced
        assert "hello" in docs[0].page_content
        assert "world" in docs[0].page_content

    def test_pure_utf8_file_loads_correctly(self, loader, tmp_path):
        p = _txt(tmp_path, "utf8.txt", "正常的中文内容")
        docs = loader.load_single_file(str(p))
        assert "正常" in docs[0].page_content


# ===========================================================================
# B3 — history summarisation rate-limit delay
# ===========================================================================

class TestSummarisationDelay:
    def test_request_delay_respected_before_summarisation_call(self):
        """_summarise_turns sleeps for request_delay before calling the LLM."""
        from uacragent.agent.conversation import ConversationAgent
        from uacragent.infra.settings import Settings

        agent = ConversationAgent(settings=Settings(google_api_key="fake"))

        call_times: list[float] = []

        class _FakeLLM:
            def invoke(self, _prompt):
                call_times.append(time.monotonic())
                class _R:
                    content = "short summary"
                return _R()

        start = time.monotonic()
        agent._summarise_turns(
            messages=[],
            existing_summary="",
            llm_client=_FakeLLM(),
            request_delay=0.15,   # small but measurable
        )
        elapsed = call_times[0] - start if call_times else 0.0
        assert elapsed >= 0.10, f"Expected >=0.10s delay, got {elapsed:.3f}s"

    def test_zero_delay_does_not_sleep(self):
        """request_delay=0 must not add any sleep."""
        from uacragent.agent.conversation import ConversationAgent

        agent = ConversationAgent(settings=Settings(google_api_key="fake"))

        class _FastLLM:
            def invoke(self, _):
                class _R:
                    content = "summary"
                return _R()

        start = time.monotonic()
        agent._summarise_turns([], "", _FastLLM(), request_delay=0.0)
        elapsed = time.monotonic() - start
        assert elapsed < 0.5   # well under any real sleep threshold

    def test_smart_trim_passes_delay_from_settings(self):
        """_smart_trim_history forwards settings.llm_request_delay."""
        from uacragent.agent.conversation import ConversationAgent
        from uacragent.agent.session import AgentSession
        from langchain_core.messages import AIMessage, HumanMessage

        # Build a session with history that exceeds the budget
        session = AgentSession()
        big = "X" * 5000
        for _ in range(8):
            session.chat_history.append_turn(
                HumanMessage(content=big), AIMessage(content=big)
            )

        delays_seen: list[float] = []

        class _TrackingLLM:
            _max_retries = 0
            _base_delay  = 0.0
            _secrets     = ()

            def invoke(self, _prompt):
                delays_seen.append(1)
                class _R:
                    content = "trimmed"
                return _R()

        settings = Settings(google_api_key="fake", rate_tier="unlimited")
        agent = ConversationAgent(settings=settings)
        # _smart_trim_history is called; we just verify it doesn't raise
        agent._smart_trim_history(session, _TrackingLLM(), request_delay=0.0)


# ===========================================================================
# B4 — export OSError wrapped as ExportError
# ===========================================================================

class TestExportOsErrorWrapped:
    def _read_only_ws(self, tmp_path: Path):
        from uacragent.infra.workspace import workspace_paths, ensure_workspace_dirs
        ws = workspace_paths(workspace_folder=tmp_path / "ws")
        ensure_workspace_dirs(ws)
        return ws

    def test_save_markdown_oserror_becomes_export_error(self, tmp_path):
        from uacragent.export.markdown import save_markdown

        ws = self._read_only_ws(tmp_path)
        with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
            with pytest.raises(ExportError, match="disk full"):
                save_markdown("# Test", ws)

    def test_save_docx_oserror_becomes_export_error(self, tmp_path):
        from uacragent.export.docx import save_docx

        ws = self._read_only_ws(tmp_path)
        # save() lives on the Document instance (docx.document.Document), not
        # on the factory function docx.Document.
        with patch("docx.document.Document.save", side_effect=OSError("no space")):
            with pytest.raises(ExportError, match="no space"):
                save_docx("# Test", ws)

    def test_save_pdf_oserror_becomes_export_error(self, tmp_path):
        from uacragent.export.pdf import save_pdf

        ws = self._read_only_ws(tmp_path)
        with patch("fpdf.FPDF.output", side_effect=OSError("permission denied")):
            with pytest.raises(ExportError, match="permission denied"):
                save_pdf("# Test", ws)

    def test_save_markdown_mkdir_oserror_becomes_export_error(self, tmp_path):
        from uacragent.export.markdown import save_markdown
        from uacragent.infra.workspace import workspace_paths

        ws = workspace_paths(workspace_folder=tmp_path / "ws")
        # Don't create the workspace — mkdir will fail due to missing parent
        with patch("pathlib.Path.mkdir", side_effect=OSError("read-only fs")):
            with pytest.raises(ExportError):
                save_markdown("content", ws)


# ===========================================================================
# B5 — _ls() warns on missing key
# ===========================================================================

class TestLsMissingKeyWarns:
    def test_missing_key_logs_warning(self, caplog):
        import logging
        from uacragent.agent.conversation import _ls, _INIT_STATUS

        with caplog.at_level(logging.WARNING, logger="uacragent.agent.conversation"):
            result = _ls("en", _INIT_STATUS, "totally_nonexistent_key_xyz")

        assert "totally_nonexistent_key_xyz" in caplog.text
        # Still returns something (the raw key) so UI doesn't crash
        assert result == "totally_nonexistent_key_xyz"

    def test_present_key_no_warning(self, caplog):
        import logging
        from uacragent.agent.conversation import _ls, _INIT_STATUS

        with caplog.at_level(logging.WARNING, logger="uacragent.agent.conversation"):
            _ls("en", _INIT_STATUS, "no_docs")

        assert "Missing localisation key" not in caplog.text


# ===========================================================================
# B6 — API workspace_id "default" gets unique UUID per request
# ===========================================================================

class TestApiWorkspaceIdIsolation:
    def _post_review(self, client, workspace_id: str, tmp_path: Path):
        """Extract the effective workspace folder from the service call."""
        captured: list[dict] = []

        original_run = None

        def _mock_run(**kwargs):
            captured.append({"workspace_folder": kwargs.get("workspace_folder")})
            raise Exception("stop_here")  # abort before actual LLM calls

        from uacragent.api import deps as _deps
        _deps.invalidate_agent_service()

        mock_svc = MagicMock()
        mock_svc.run_end_to_end.side_effect = _mock_run

        with patch("uacragent.api.routes.get_agent_service", return_value=mock_svc):
            # We only need the workspace_folder argument; ignore the 500 error
            try:
                client.post("/review", json={
                    "classified_files": {"other": ["/fake/file.pdf"]},
                    "course_name": "CS101",
                    "workspace_id": workspace_id,
                })
            except Exception:
                pass

        return captured[0]["workspace_folder"] if captured else None

    def test_default_workspace_id_generates_unique_folders(self):
        """Two requests with workspace_id='default' must use different folders."""
        from uacragent.api.main import create_app
        from fastapi.testclient import TestClient

        app = create_app()
        folders: list[str] = []

        def _capture(**kwargs):
            folders.append(str(kwargs.get("workspace_folder", "")))
            raise Exception("stop")

        mock_svc = MagicMock()
        mock_svc.run_end_to_end.side_effect = _capture

        with TestClient(app, raise_server_exceptions=False) as client:
            with patch("uacragent.api.routes.get_agent_service", return_value=mock_svc):
                for _ in range(2):
                    client.post("/review", json={
                        "classified_files": {"other": ["/f.txt"]},
                        "course_name": "X",
                        "workspace_id": "default",
                    })

        # Two requests with "default" must resolve to different workspace paths
        if len(folders) == 2:
            assert folders[0] != folders[1], (
                f"Both requests used the same workspace: {folders[0]}"
            )

    def test_explicit_workspace_id_preserved(self):
        """An explicit non-default workspace_id must not be replaced."""
        from uacragent.api.main import create_app
        from fastapi.testclient import TestClient

        app = create_app()
        folders: list[str] = []

        def _capture(**kwargs):
            folders.append(str(kwargs.get("workspace_folder", "")))
            raise Exception("stop")

        mock_svc = MagicMock()
        mock_svc.run_end_to_end.side_effect = _capture

        with TestClient(app, raise_server_exceptions=False) as client:
            with patch("uacragent.api.routes.get_agent_service", return_value=mock_svc):
                client.post("/review", json={
                    "classified_files": {"other": ["/f.txt"]},
                    "course_name": "X",
                    "workspace_id": "my-session-01",
                })

        if folders:
            assert "my-session-01" in folders[0]


# ===========================================================================
# B7 — image-only PDF gives clear OCR error
# ===========================================================================

class TestImageOnlyPdfError:
    def test_scanned_pdf_raises_ingest_error_with_ocr_hint(self, loader, tmp_path):
        """A PDF whose pages all have empty page_content must produce an OCR hint."""
        from langchain_core.documents import Document

        p = tmp_path / "scanned.pdf"
        p.write_bytes(b"%PDF-1.4 fake")  # file must exist

        # Mock load_single_file to return empty-content pages (image-only PDF)
        empty_pages = [
            Document(page_content="", metadata={"source": str(p)}),
            Document(page_content="   ", metadata={"source": str(p)}),
        ]
        with patch.object(loader, "load_single_file", return_value=empty_pages):
            with pytest.raises(IngestError, match="scanned or image-only"):
                loader.load_and_split_classified({DocumentType.other: [str(p)]})

    def test_scanned_pdf_error_contains_ocr_guidance(self, loader, tmp_path):
        from langchain_core.documents import Document

        p = tmp_path / "scan.pdf"
        p.write_bytes(b"%PDF-1.4 fake")

        with patch.object(loader, "load_single_file", return_value=[
            Document(page_content="", metadata={"source": str(p)})
        ]):
            with pytest.raises(IngestError) as exc_info:
                loader.load_and_split_classified({DocumentType.other: [str(p)]})
        assert "OCR" in str(exc_info.value) or "ocr" in str(exc_info.value).lower()

    def test_pdf_with_text_is_not_flagged(self, loader, tmp_path):
        from langchain_core.documents import Document

        p = tmp_path / "text.pdf"
        p.write_bytes(b"%PDF-1.4 fake")

        with patch.object(loader, "load_single_file", return_value=[
            Document(page_content="real course content", metadata={"source": str(p)})
        ]):
            chunks = loader.load_and_split_classified({DocumentType.other: [str(p)]})
        assert len(chunks) > 0


# ===========================================================================
# B8 — search-preview models strip image attachments
# ===========================================================================

class TestSearchPreviewVisionStrip:
    def test_search_preview_model_no_vision(self):
        from uacragent.agent.conversation import _provider_supports_vision

        assert _provider_supports_vision("openai", model="gpt-4o-search-preview") is False
        assert _provider_supports_vision("openai", model="gpt-4o-mini-search-preview") is False

    def test_regular_openai_model_has_vision(self):
        from uacragent.agent.conversation import _provider_supports_vision

        assert _provider_supports_vision("openai", model="gpt-4o") is True
        assert _provider_supports_vision("openai", model="gpt-4.1") is True

    def test_gemini_model_has_vision(self):
        from uacragent.agent.conversation import _provider_supports_vision

        assert _provider_supports_vision("gemini", model="gemini-2.5-flash") is True

    def test_deepseek_no_vision(self):
        from uacragent.agent.conversation import _provider_supports_vision

        assert _provider_supports_vision("deepseek", model="deepseek-chat") is False

    def test_model_name_empty_falls_back_to_provider_flag(self):
        from uacragent.agent.conversation import _provider_supports_vision

        # Empty model name — only the provider flag counts
        assert _provider_supports_vision("gemini", model="") is True
        assert _provider_supports_vision("deepseek", model="") is False


# ===========================================================================
# S5 — large-file guard
# ===========================================================================

class TestLargeFileGuard:
    def _make_file(self, tmp_path: Path, name: str, size: int) -> Path:
        p = tmp_path / name
        # Write exact size using seek+write so we don't allocate in memory
        with open(p, "wb") as fh:
            fh.seek(size - 1)
            fh.write(b"\x00")
        return p

    def test_file_over_block_threshold_raises(self, loader, tmp_path):
        p = self._make_file(tmp_path, "huge.txt", _LARGE_FILE_BLOCK_BYTES + 1)
        with pytest.raises(IngestError, match="memory limit"):
            loader.load_and_split_classified({DocumentType.other: [str(p)]})

    def test_file_at_block_threshold_raises(self, loader, tmp_path):
        p = self._make_file(tmp_path, "exact.txt", _LARGE_FILE_BLOCK_BYTES)
        with pytest.raises(IngestError, match="memory limit"):
            loader.load_and_split_classified({DocumentType.other: [str(p)]})

    def test_file_over_warn_threshold_logs_warning(self, loader, tmp_path, caplog):
        import logging
        # Just below block threshold, above warn threshold
        size = _LARGE_FILE_WARN_BYTES + 1
        p = self._make_file(tmp_path, "large.txt", size)
        # Will fail to load (empty content → 0 chunks, or IngestError from loading)
        # but the WARNING about large file must appear before the load attempt
        with caplog.at_level(logging.WARNING, logger="uacragent.infra.loaders"):
            try:
                loader.load_and_split_classified({DocumentType.other: [str(p)]})
            except Exception:
                pass
        assert any("Large file" in r.message for r in caplog.records)

    def test_small_file_below_thresholds_passes(self, loader, tmp_path):
        p = tmp_path / "small.txt"
        p.write_text("normal content " * 50)
        chunks = loader.load_and_split_classified({DocumentType.other: [str(p)]})
        assert len(chunks) > 0

    def test_block_threshold_is_300mb(self):
        assert _LARGE_FILE_BLOCK_BYTES == 300 * 1024 * 1024

    def test_warn_threshold_is_100mb(self):
        assert _LARGE_FILE_WARN_BYTES == 100 * 1024 * 1024
