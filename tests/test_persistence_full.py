"""Full coverage for infra/persistence.py — serialisation, session I/O, index."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from uacragent.agent.session import AgentSession
from uacragent.domain.types import DocumentType
from uacragent.infra import persistence as pers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(tmp_path: Path, **kwargs) -> tuple[AgentSession, Path]:
    ws_folder = tmp_path / "myws"
    ws_folder.mkdir(parents=True)
    s = AgentSession(workspace_folder=ws_folder, workspace_id="test-id", **kwargs)
    return s, ws_folder


# ---------------------------------------------------------------------------
# _serialise_history / _deserialise_history
# ---------------------------------------------------------------------------

class TestHistorySerialisation:
    def test_round_trip_human_ai_pairs(self):
        msgs = [
            HumanMessage(content="hello"),
            AIMessage(content="world"),
        ]
        serialised = pers._serialise_history(msgs)
        restored = pers._deserialise_history(serialised)
        assert len(restored) == 2
        assert restored[0].content == "hello"
        assert restored[1].content == "world"

    def test_human_additional_kwargs_preserved(self):
        msg = HumanMessage(content="q", additional_kwargs={"files": ["a.pdf"]})
        serialised = pers._serialise_history([msg])
        restored = pers._deserialise_history(serialised)
        assert restored[0].additional_kwargs == {"files": ["a.pdf"]}

    def test_unknown_role_skipped(self):
        data = [{"role": "system", "content": "you are helpful"}]
        restored = pers._deserialise_history(data)
        assert len(restored) == 0

    def test_empty_history_round_trips(self):
        assert pers._serialise_history([]) == []
        assert pers._deserialise_history([]) == []

    def test_multiple_turns(self):
        msgs = []
        for i in range(5):
            msgs.append(HumanMessage(content=f"q{i}"))
            msgs.append(AIMessage(content=f"a{i}"))
        serialised = pers._serialise_history(msgs)
        restored = pers._deserialise_history(serialised)
        assert len(restored) == 10
        assert restored[4].content == "q2"


# ---------------------------------------------------------------------------
# _serialise_files / _deserialise_files
# ---------------------------------------------------------------------------

class TestFileSerialisation:
    def test_round_trip(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("hello")
        classified = {DocumentType.lecture_note: [str(f)]}
        serialised = pers._serialise_files(classified)
        assert serialised == {"lecture_note": [str(f)]}

    def test_deserialise_skips_nonexistent_files(self, tmp_path):
        data = {"lecture_note": ["/totally/fake/path.pdf"]}
        result = pers._deserialise_files(data)
        assert result == {}

    def test_deserialise_skips_unknown_doc_type(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("hello")
        data = {"unknown_type_xyz": [str(f)]}
        result = pers._deserialise_files(data)
        assert result == {}

    def test_deserialise_filters_nonexistent_from_mixed_list(self, tmp_path):
        existing = tmp_path / "exists.txt"
        existing.write_text("ok")
        data = {"other": [str(existing), "/gone.pdf"]}
        result = pers._deserialise_files(data)
        assert str(existing) in result[DocumentType.other]
        assert "/gone.pdf" not in result[DocumentType.other]


# ---------------------------------------------------------------------------
# save_session / load_session
# ---------------------------------------------------------------------------

class TestSessionIO:
    def test_save_creates_session_json(self, tmp_path):
        s, ws = _make_session(tmp_path, course_name="CS101")
        ok = pers.save_session(s)
        assert ok is True
        session_file = ws / ".uacragent" / "session.json"
        assert session_file.exists()

    def test_save_and_load_round_trip(self, tmp_path):
        s, ws = _make_session(tmp_path, course_name="Data Structures", exam_type="midterm")
        pers.save_session(s)
        data = pers.load_session(ws)
        assert data is not None
        assert data["course_name"] == "Data Structures"
        assert data["exam_type"] == "midterm"

    def test_api_keys_never_written(self, tmp_path):
        s, ws = _make_session(tmp_path)
        pers.save_session(s, ui_extras={"google_api_key": "SECRET", "openai_api_key": "ALSO_SECRET"})
        session_file = ws / ".uacragent" / "session.json"
        raw = session_file.read_text()
        assert "SECRET" not in raw
        assert "ALSO_SECRET" not in raw

    def test_ui_extras_non_key_preserved(self, tmp_path):
        s, ws = _make_session(tmp_path)
        pers.save_session(s, ui_extras={"theme": "dark", "font_size": "large"})
        data = pers.load_session(ws)
        assert data["theme"] == "dark"
        assert data["font_size"] == "large"

    def test_load_nonexistent_returns_none(self, tmp_path):
        result = pers.load_session(tmp_path / "no_such_session")
        assert result is None

    def test_load_version_mismatch_flagged(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        agent_dir = ws / ".uacragent"
        agent_dir.mkdir()
        (agent_dir / "session.json").write_text(
            json.dumps({"version": 99, "course_name": "X"}), encoding="utf-8"
        )
        data = pers.load_session(ws)
        assert data is not None
        assert data.get("_version_mismatch") is True

    def test_chat_history_persisted(self, tmp_path):
        s, ws = _make_session(tmp_path)
        s.chat_history.append_turn(HumanMessage(content="q1"), AIMessage(content="a1"))
        pers.save_session(s)
        data = pers.load_session(ws)
        assert len(data["chat_history"]) == 2
        assert data["chat_history"][0]["content"] == "q1"


# ---------------------------------------------------------------------------
# dict_to_session
# ---------------------------------------------------------------------------

class TestDictToSession:
    def test_basic_round_trip(self):
        d = {
            "workspace_id": "abc123",
            "course_name": "Algorithms",
            "exam_type": "final",
            "llm_provider": "gemini",
        }
        s = pers.dict_to_session(d)
        assert s.course_name == "Algorithms"
        assert s.workspace_id == "abc123"

    def test_path_traversal_workspace_id_rejected(self):
        d = {"workspace_id": "../../etc/passwd", "llm_provider": "gemini"}
        s = pers.dict_to_session(d)
        assert "../" not in s.workspace_id

    def test_unknown_llm_provider_falls_back(self):
        d = {"workspace_id": "safe", "llm_provider": "evil_corp"}
        s = pers.dict_to_session(d)
        assert s.llm_provider == "gemini"

    def test_empty_workspace_id_gets_fresh_id(self):
        d = {"workspace_id": "", "llm_provider": "openai"}
        s = pers.dict_to_session(d)
        assert s.workspace_id != ""

    def test_all_known_providers_accepted(self):
        for provider in ("gemini", "openai", "deepseek"):
            d = {"workspace_id": "x", "llm_provider": provider}
            s = pers.dict_to_session(d)
            assert s.llm_provider == provider


# ---------------------------------------------------------------------------
# get_missing_session_files
# ---------------------------------------------------------------------------

class TestGetMissingSessionFiles:
    def test_all_present_returns_empty(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("ok")
        data = {"classified_files": {"lecture_note": [str(f)]}}
        assert pers.get_missing_session_files(data) == []

    def test_missing_file_detected(self, tmp_path):
        data = {"classified_files": {"lecture_note": ["/totally/gone.pdf"]}}
        missing = pers.get_missing_session_files(data)
        assert "/totally/gone.pdf" in missing

    def test_empty_data_returns_empty(self):
        assert pers.get_missing_session_files({}) == []


# ---------------------------------------------------------------------------
# Atomic write helper
# ---------------------------------------------------------------------------

class TestAtomicWrite:
    def test_writes_content(self, tmp_path):
        p = tmp_path / "out.txt"
        pers._atomic_write_text(p, "hello world")
        assert p.read_text() == "hello world"

    def test_no_tmp_file_left_on_success(self, tmp_path):
        p = tmp_path / "out.txt"
        pers._atomic_write_text(p, "data")
        tmp = p.with_suffix(".tmp")
        assert not tmp.exists()

    def test_overwrites_existing(self, tmp_path):
        p = tmp_path / "out.txt"
        p.write_text("old")
        pers._atomic_write_text(p, "new")
        assert p.read_text() == "new"
