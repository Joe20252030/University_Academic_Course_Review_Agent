"""Extended loader tests covering cross-type dedup, attachment handling, and edge cases."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.documents import Document

from uacragent.domain.types import DocumentType
from uacragent.infra.loaders import DocumentLoader
from uacragent.infra.settings import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(google_api_key="fake-key-for-tests", workspace_root=tmp_path)


@pytest.fixture
def loader(settings: Settings) -> DocumentLoader:
    return DocumentLoader(settings)


# ---------------------------------------------------------------------------
# load_and_split_classified — cross-type deduplication
# ---------------------------------------------------------------------------

class TestCrossTypeDedup:
    def test_same_file_two_types_indexed_once(self, loader, tmp_path):
        """The same physical file under two doc types must only be processed once."""
        from uacragent.infra.workspace import workspace_paths, ensure_workspace_dirs

        src = tmp_path / "notes.txt"
        src.write_text("unique course content")

        ws = workspace_paths(workspace_folder=tmp_path / "ws")
        ensure_workspace_dirs(ws)

        classified = {
            DocumentType.lecture_note: [str(src)],
            DocumentType.syllabus:     [str(src)],   # same file, different type
        }
        chunks = loader.load_and_split_classified(classified, workspace_paths=ws)

        # Content appears exactly once — the second type's copy is skipped
        texts = [c.page_content for c in chunks]
        assert len(texts) >= 1
        # No chunk from the second type should be present (no double content)
        # All chunks should reference the lecture_note upload folder
        sources = [c.metadata.get("source", "") for c in chunks]
        assert all("lecture_note" in s for s in sources), (
            f"Expected all sources under lecture_note, got: {sources}"
        )

    def test_different_files_two_types_both_indexed(self, loader, tmp_path):
        """Two different files under two different types must both be indexed."""
        from uacragent.infra.workspace import workspace_paths, ensure_workspace_dirs

        f1 = tmp_path / "notes1.txt"
        f1.write_text("content from lecture notes")
        f2 = tmp_path / "syllabus.txt"
        f2.write_text("content from syllabus")

        ws = workspace_paths(workspace_folder=tmp_path / "ws")
        ensure_workspace_dirs(ws)

        classified = {
            DocumentType.lecture_note: [str(f1)],
            DocumentType.syllabus:     [str(f2)],
        }
        chunks = loader.load_and_split_classified(classified, workspace_paths=ws)

        # Both files should contribute chunks
        all_text = " ".join(c.page_content for c in chunks)
        assert "lecture notes" in all_text
        assert "syllabus" in all_text

    def test_same_file_same_type_deduplicated_once(self, loader, tmp_path):
        """The same path listed twice within one type is only processed once."""
        from uacragent.infra.workspace import workspace_paths, ensure_workspace_dirs

        src = tmp_path / "dup.txt"
        src.write_text("some content")

        ws = workspace_paths(workspace_folder=tmp_path / "ws")
        ensure_workspace_dirs(ws)

        classified = {
            DocumentType.other: [str(src), str(src)],   # listed twice
        }
        chunks = loader.load_and_split_classified(classified, workspace_paths=ws)

        # Should only produce chunks for one copy
        sources = [c.metadata.get("source", "") for c in chunks]
        unique_sources = set(sources)
        assert len(unique_sources) == 1


# ---------------------------------------------------------------------------
# copy_to_workspace — edge cases
# ---------------------------------------------------------------------------

class TestCopyToWorkspaceEdgeCases:
    def test_missing_source_raises(self, loader, tmp_path):
        from uacragent.infra.workspace import workspace_paths, ensure_workspace_dirs
        from uacragent.domain.errors import IngestError

        ws = workspace_paths(workspace_folder=tmp_path / "ws")
        ensure_workspace_dirs(ws)

        with pytest.raises(IngestError, match="Source file not found"):
            loader.copy_to_workspace(
                str(tmp_path / "nonexistent.pdf"),
                DocumentType.other,
                ws,
            )

    def test_reuses_identical_content_after_multiple_calls(self, loader, tmp_path):
        """Calling copy_to_workspace three times with same content returns same path."""
        from uacragent.infra.workspace import workspace_paths, ensure_workspace_dirs

        src = tmp_path / "report.txt"
        src.write_text("immutable report content")
        ws = workspace_paths(workspace_folder=tmp_path / "ws")
        ensure_workspace_dirs(ws)

        dest1 = loader.copy_to_workspace(str(src), DocumentType.other, ws)
        dest2 = loader.copy_to_workspace(str(src), DocumentType.other, ws)
        dest3 = loader.copy_to_workspace(str(src), DocumentType.other, ws)

        assert dest1 == dest2 == dest3
        # Only one physical file should exist
        folder = Path(dest1).parent
        txt_files = list(folder.glob("*.txt"))
        assert len(txt_files) == 1

    def test_different_content_same_name_gets_suffix(self, loader, tmp_path):
        """Two files with same name but different content → second gets _1 suffix."""
        from uacragent.infra.workspace import workspace_paths, ensure_workspace_dirs

        dir_a = tmp_path / "a"
        dir_a.mkdir()
        dir_b = tmp_path / "b"
        dir_b.mkdir()

        (dir_a / "file.txt").write_text("content A")
        (dir_b / "file.txt").write_text("content B — different")

        ws = workspace_paths(workspace_folder=tmp_path / "ws")
        ensure_workspace_dirs(ws)

        dest1 = loader.copy_to_workspace(str(dir_a / "file.txt"), DocumentType.other, ws)
        dest2 = loader.copy_to_workspace(str(dir_b / "file.txt"), DocumentType.other, ws)

        assert dest1 != dest2
        assert Path(dest2).name == "file_1.txt"
        assert Path(dest1).read_text() == "content A"
        assert Path(dest2).read_text() == "content B — different"


# ---------------------------------------------------------------------------
# _extract_file_text — unsupported MIME
# ---------------------------------------------------------------------------

class TestExtractFileText:
    def test_unsupported_mime_returns_error_block(self, tmp_path):
        """application/octet-stream must return a clearly-marked error block and a ui_warning."""
        from uacragent.agent.conversation import _extract_file_text

        f = tmp_path / "data.xlsx"
        f.write_bytes(b"\x00\x01\x02binary")

        llm_text, ui_warning = _extract_file_text(str(f), "application/octet-stream")

        assert "UNSUPPORTED FILE TYPE" in llm_text
        assert "data.xlsx" in llm_text
        assert ui_warning is not None
        assert "data.xlsx" in ui_warning

    def test_text_plain_reads_content(self, tmp_path):
        from uacragent.agent.conversation import _extract_file_text

        f = tmp_path / "notes.txt"
        f.write_text("hello from notes", encoding="utf-8")

        llm_text, ui_warning = _extract_file_text(str(f), "text/plain")
        assert "hello from notes" in llm_text
        assert ui_warning is None  # success — no warning

    def test_missing_file_returns_error_block(self, tmp_path):
        from uacragent.agent.conversation import _extract_file_text

        llm_text, ui_warning = _extract_file_text(str(tmp_path / "gone.txt"), "text/plain")
        assert "FILE EXTRACTION ERROR" in llm_text
        assert ui_warning is not None
        assert "gone.txt" in ui_warning


# ---------------------------------------------------------------------------
# _build_human_message — attachment limits
# ---------------------------------------------------------------------------

class TestBuildHumanMessageLimits:
    def _make_image_att(self, tmp_path: Path, name: str = "img.png") -> dict:
        f = tmp_path / name
        f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        return {"path": str(f), "name": name, "mime": "image/png"}

    def test_no_attachments_returns_plain_human_message(self, tmp_path):
        from uacragent.agent.conversation import _build_human_message

        msg, warnings = _build_human_message("hello", [], "gemini")
        assert msg.content == "hello"
        assert warnings == []

    def test_max_attachments_cap_at_five(self, tmp_path):
        from uacragent.agent.conversation import _build_human_message

        # Create 6 small text attachments
        atts = []
        for i in range(6):
            f = tmp_path / f"file{i}.txt"
            f.write_text(f"content {i}")
            atts.append({"path": str(f), "name": f"file{i}.txt", "mime": "text/plain"})

        _, warnings = _build_human_message("test", atts, "gemini")
        # Should warn about dropped attachment(s)
        assert any("1" in w or "attachment" in w.lower() for w in warnings)

    def test_oversized_file_skipped_with_warning(self, tmp_path):
        from uacragent.agent.conversation import _build_human_message

        # Create a file that appears larger than 10 MB by patching stat
        f = tmp_path / "huge.txt"
        f.write_text("small content")

        with patch("pathlib.Path.stat") as mock_stat:
            mock_stat.return_value = MagicMock(st_size=11 * 1024 * 1024)
            att = {"path": str(f), "name": "huge.txt", "mime": "text/plain"}
            _, warnings = _build_human_message("msg", [att], "gemini")

        assert any("huge.txt" in w for w in warnings)

    def test_text_budget_exhaustion_warns(self, tmp_path):
        from uacragent.agent.conversation import _build_human_message, _MAX_EXTRACTED_TEXT_CHARS

        # Two files whose combined content exceeds the budget
        f1 = tmp_path / "big1.txt"
        f2 = tmp_path / "big2.txt"
        # Each is just over half the budget
        half = _MAX_EXTRACTED_TEXT_CHARS // 2 + 100
        f1.write_text("A" * half)
        f2.write_text("B" * half)

        atts = [
            {"path": str(f1), "name": "big1.txt", "mime": "text/plain"},
            {"path": str(f2), "name": "big2.txt", "mime": "text/plain"},
        ]
        _, warnings = _build_human_message("q", atts, "gemini")

        # Second file should be warned about budget exhaustion
        assert any("big2.txt" in w or "budget" in w.lower() for w in warnings)


# ---------------------------------------------------------------------------
# Session persistence — workspace_id safety
# ---------------------------------------------------------------------------

class TestWorkspaceIdSafety:
    def test_valid_id_accepted(self):
        from uacragent.infra.persistence import dict_to_session

        d = {
            "workspace_id": "my-session-01",
            "workspace": "/tmp/ws",
            "llm_provider": "gemini",
        }
        session = dict_to_session(d)
        assert session.workspace_id == "my-session-01"

    def test_path_traversal_id_rejected(self):
        """A workspace_id with path-traversal characters must be replaced with a UUID."""
        from uacragent.infra.persistence import dict_to_session

        d = {
            "workspace_id": "../../etc/passwd",
            "workspace": "/tmp/ws",
            "llm_provider": "gemini",
        }
        session = dict_to_session(d)
        # Must NOT keep the traversal string
        assert "../" not in session.workspace_id
        assert "etc" not in session.workspace_id
        # Should be a valid UUID-style replacement
        assert len(session.workspace_id) > 0

    def test_unknown_provider_falls_back(self):
        """An unrecognised llm_provider in session data must be replaced with the default."""
        from uacragent.infra.persistence import dict_to_session

        d = {
            "workspace_id": "abc123",
            "workspace": "/tmp/ws",
            "llm_provider": "evil_provider_xyz",
        }
        session = dict_to_session(d)
        # Must not keep the unknown provider
        assert session.llm_provider != "evil_provider_xyz"

    def test_api_keys_not_persisted(self, tmp_path):
        """API keys must never appear in the serialised session JSON."""
        import json
        from uacragent.infra.persistence import save_session, load_session
        from uacragent.infra.workspace import workspace_paths, ensure_workspace_dirs
        from uacragent.agent.session import AgentSession

        ws_folder = tmp_path / "safe-id"
        ws = workspace_paths(workspace_folder=ws_folder)
        ensure_workspace_dirs(ws)

        s = AgentSession(workspace_folder=ws_folder, workspace_id="safe-id")
        # Pass a google_api_key as a ui_extra — it must be filtered out before writing.
        save_session(s, ui_extras={"google_api_key": "secret-key", "course": "CS"})

        # Read the raw JSON and verify the key is absent
        session_file = ws_folder / ".uacragent" / "session.json"
        raw = session_file.read_text(encoding="utf-8")
        assert "secret-key" not in raw
        assert "google_api_key" not in raw
        # Non-key extra should be preserved
        data = json.loads(raw)
        assert data.get("course") == "CS"


# needed for the patch import
from unittest.mock import MagicMock  # noqa: E402
