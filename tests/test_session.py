"""Tests for agent/session.py — AgentSession and _HistoryStore."""
from __future__ import annotations

import threading
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from uacragent.agent.session import AgentSession, _HistoryStore
from uacragent.domain.types import DocumentType


# ---------------------------------------------------------------------------
# _HistoryStore — basic operations
# ---------------------------------------------------------------------------

class TestHistoryStore:
    def test_starts_empty(self):
        hs = _HistoryStore()
        assert len(hs) == 0
        assert not hs

    def test_append_turn_adds_pair(self):
        hs = _HistoryStore()
        hs.append_turn(HumanMessage(content="hi"), AIMessage(content="hello"))
        assert len(hs) == 2

    def test_pop_last_turn_removes_pair(self):
        hs = _HistoryStore()
        hs.append_turn(HumanMessage(content="a"), AIMessage(content="b"))
        removed = hs.pop_last_turn()
        assert removed is True
        assert len(hs) == 0

    def test_pop_last_turn_on_empty_returns_false(self):
        hs = _HistoryStore()
        assert hs.pop_last_turn() is False

    def test_pop_last_ai_only_removes_ai_message(self):
        hs = _HistoryStore()
        hs.append_turn(HumanMessage(content="q"), AIMessage(content="a"))
        removed = hs.pop_last_ai_only()
        assert removed is True
        assert len(hs) == 1
        assert isinstance(hs[0], HumanMessage)

    def test_pop_last_ai_only_on_empty_returns_false(self):
        hs = _HistoryStore()
        assert hs.pop_last_ai_only() is False

    def test_pop_last_ai_only_when_last_is_human_returns_false(self):
        hs = _HistoryStore()
        hs.append_human_only(HumanMessage(content="q"))
        assert hs.pop_last_ai_only() is False
        assert len(hs) == 1

    def test_append_human_only(self):
        hs = _HistoryStore()
        hs.append_human_only(HumanMessage(content="pending"))
        assert len(hs) == 1
        assert isinstance(hs[0], HumanMessage)

    def test_replace_all(self):
        hs = _HistoryStore()
        hs.append_turn(HumanMessage(content="a"), AIMessage(content="b"))
        new_msgs = [HumanMessage(content="x"), AIMessage(content="y"),
                    HumanMessage(content="z"), AIMessage(content="w")]
        hs.replace_all(new_msgs)
        assert len(hs) == 4

    def test_snapshot_is_copy(self):
        hs = _HistoryStore()
        hs.append_turn(HumanMessage(content="a"), AIMessage(content="b"))
        snap = hs.snapshot()
        snap.clear()
        assert len(hs) == 2  # original unaffected

    def test_clear(self):
        hs = _HistoryStore()
        hs.append_turn(HumanMessage(content="a"), AIMessage(content="b"))
        hs.clear()
        assert len(hs) == 0

    def test_iteration_is_safe(self):
        hs = _HistoryStore()
        hs.append_turn(HumanMessage(content="a"), AIMessage(content="b"))
        msgs = list(hs)
        assert len(msgs) == 2

    def test_getitem(self):
        hs = _HistoryStore()
        hs.append_turn(HumanMessage(content="q"), AIMessage(content="a"))
        assert hs[0].content == "q"
        assert hs[-1].content == "a"

    def test_bool_false_when_empty(self):
        assert not _HistoryStore()

    def test_bool_true_when_not_empty(self):
        hs = _HistoryStore()
        hs.append_human_only(HumanMessage(content="x"))
        assert hs

    def test_initialise_from_list(self):
        msgs = [HumanMessage(content="a"), AIMessage(content="b")]
        hs = _HistoryStore(msgs)
        assert len(hs) == 2

    def test_concurrent_append_is_safe(self):
        """Multiple threads appending turns must not corrupt the store."""
        hs = _HistoryStore()
        errors = []

        def _worker(n: int) -> None:
            try:
                for _ in range(n):
                    hs.append_turn(HumanMessage(content="h"), AIMessage(content="a"))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=_worker, args=(50,)) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(hs) % 2 == 0   # always even (pairs)


# ---------------------------------------------------------------------------
# AgentSession
# ---------------------------------------------------------------------------

class TestAgentSession:
    def test_defaults(self):
        s = AgentSession()
        assert s.course_name == ""
        assert s.exam_type == "final"
        assert s.llm_provider == "gemini"
        assert isinstance(s.chat_history, _HistoryStore)

    def test_workspace_id_auto_generated(self):
        s = AgentSession()
        assert len(s.workspace_id) == 12
        assert s.workspace_id.isalnum()

    def test_has_files_false_when_empty(self):
        s = AgentSession()
        assert s.has_files() is False

    def test_has_files_true_when_files_present(self):
        s = AgentSession(classified_files={
            DocumentType.syllabus: ["/f/syllabus.pdf"]
        })
        assert s.has_files() is True

    def test_has_files_false_all_empty_lists(self):
        s = AgentSession(classified_files={
            DocumentType.syllabus: [],
            DocumentType.lecture_note: [],
        })
        assert s.has_files() is False

    def test_active_files_filters_empty_buckets(self):
        s = AgentSession(classified_files={
            DocumentType.syllabus: ["/f/a.pdf"],
            DocumentType.lecture_note: [],
        })
        active = s.active_files()
        assert DocumentType.syllabus in active
        assert DocumentType.lecture_note not in active

    def test_to_user_prefs_keys(self):
        s = AgentSession(
            course_name="CS101",
            university_name="UofT",
            exam_type="final",
        )
        prefs = s.to_user_prefs()
        required_keys = {
            "course_name", "university_name", "major", "course_code",
            "professor_name", "semester", "exam_type", "exam_format",
            "exam_duration", "exam_info", "workspace_id", "extra_instructions",
        }
        assert required_keys.issubset(prefs.keys())
        assert prefs["course_name"] == "CS101"

    def test_chat_history_wrapped_from_list(self):
        msgs = [HumanMessage(content="q"), AIMessage(content="a")]
        s = AgentSession(chat_history=msgs)  # type: ignore[arg-type]
        assert isinstance(s.chat_history, _HistoryStore)
        assert len(s.chat_history) == 2

    def test_read_exam_info_empty_when_no_path(self):
        s = AgentSession()
        assert s.read_exam_info() == ""

    def test_read_exam_info_reads_text_file(self, tmp_path):
        f = tmp_path / "info.txt"
        f.write_text("Closed book exam. Formula sheet allowed.", encoding="utf-8")
        s = AgentSession(exam_info_path=str(f))
        content = s.read_exam_info()
        assert "Closed book" in content

    def test_read_exam_info_cached(self, tmp_path):
        f = tmp_path / "info.txt"
        f.write_text("content", encoding="utf-8")
        s = AgentSession(exam_info_path=str(f))
        content1 = s.read_exam_info()
        # Overwrite file — cached result should be returned
        f.write_text("CHANGED", encoding="utf-8")
        content2 = s.read_exam_info()
        assert content1 == content2 == "content"

    def test_read_exam_info_truncated_when_oversized(self, tmp_path):
        f = tmp_path / "big.txt"
        oversized_content = "X" * (AgentSession._EXAM_INFO_MAX_CHARS + 500)
        f.write_text(oversized_content, encoding="utf-8")
        s = AgentSession(exam_info_path=str(f))
        content = s.read_exam_info()
        assert len(content) == AgentSession._EXAM_INFO_MAX_CHARS

    def test_is_exam_info_oversized_false_for_small_file(self, tmp_path):
        f = tmp_path / "small.txt"
        f.write_text("short content", encoding="utf-8")
        s = AgentSession(exam_info_path=str(f))
        assert s.is_exam_info_oversized() is False

    def test_is_exam_info_oversized_true_for_large_file(self, tmp_path):
        f = tmp_path / "huge.txt"
        f.write_text("Y" * (AgentSession._EXAM_INFO_MAX_CHARS + 1), encoding="utf-8")
        s = AgentSession(exam_info_path=str(f))
        assert s.is_exam_info_oversized() is True

    def test_is_exam_info_oversized_false_when_no_path(self):
        s = AgentSession()
        assert s.is_exam_info_oversized() is False
