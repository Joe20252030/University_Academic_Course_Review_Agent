"""Tests for the FastAPI layer: schemas, path validation, health, error handlers."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from uacragent.api.main import create_app
from uacragent.api.schemas import ClassifiedFiles, ReviewRequest
from uacragent.domain.types import DocumentType


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# ClassifiedFiles schema
# ---------------------------------------------------------------------------

class TestClassifiedFiles:
    def test_empty_is_empty(self):
        cf = ClassifiedFiles()
        assert cf.is_empty() is True

    def test_one_file_not_empty(self):
        cf = ClassifiedFiles(syllabus=["/a/b.pdf"])
        assert cf.is_empty() is False

    def test_to_dict_omits_empty_buckets(self):
        cf = ClassifiedFiles(syllabus=["/a/b.pdf"], lecture_note=[])
        d = cf.to_dict()
        assert DocumentType.syllabus in d
        assert DocumentType.lecture_note not in d

    def test_to_dict_all_types(self):
        cf = ClassifiedFiles(
            syllabus=["/a/s.pdf"],
            lecture_note=["/a/l.pdf"],
            textbook=["/a/t.pdf"],
            assignment=["/a/a.pdf"],
            past_exam=["/a/e.pdf"],
            other=["/a/o.pdf"],
        )
        d = cf.to_dict()
        assert len(d) == 6

    def test_to_dict_returns_correct_lists(self):
        cf = ClassifiedFiles(past_exam=["/x/exam.pdf"])
        d = cf.to_dict()
        assert d[DocumentType.past_exam] == ["/x/exam.pdf"]


# ---------------------------------------------------------------------------
# ReviewRequest schema validation
# ---------------------------------------------------------------------------

class TestReviewRequest:
    def test_valid_workspace_id_accepted(self):
        req = ReviewRequest(
            classified_files=ClassifiedFiles(),
            course_name="CS101",
            workspace_id="my-session-01",
        )
        assert req.workspace_id == "my-session-01"

    def test_invalid_workspace_id_rejected(self):
        with pytest.raises(Exception):
            ReviewRequest(
                classified_files=ClassifiedFiles(),
                course_name="CS101",
                workspace_id="../../etc",
            )

    def test_effort_level_pattern_enforced(self):
        with pytest.raises(Exception):
            ReviewRequest(
                classified_files=ClassifiedFiles(),
                course_name="CS101",
                effort_level="ultramax",
            )

    def test_reasoning_mode_pattern_enforced(self):
        with pytest.raises(Exception):
            ReviewRequest(
                classified_files=ClassifiedFiles(),
                course_name="CS101",
                reasoning_mode="turbo",
            )

    def test_course_name_min_length_enforced(self):
        with pytest.raises(Exception):
            ReviewRequest(
                classified_files=ClassifiedFiles(),
                course_name="",
            )


# ---------------------------------------------------------------------------
# _validate_file_paths — path security
# ---------------------------------------------------------------------------

class TestValidateFilePaths:
    """Test the path validation logic directly (not via HTTP to keep tests fast)."""

    def _call(self, classified_dict: dict, base_dir: str | None = None):
        from uacragent.api.routes import _validate_file_paths
        from fastapi import HTTPException

        env_patch = (
            patch.dict(os.environ, {"UACRAGENT_ALLOWED_BASE_DIR": base_dir})
            if base_dir is not None
            else patch.dict(os.environ, {}, clear=False)
        )
        with env_patch:
            _validate_file_paths(classified_dict)

    def test_relative_path_rejected(self, tmp_path):
        from fastapi import HTTPException
        from uacragent.api.routes import _validate_file_paths

        with pytest.raises(HTTPException) as exc_info:
            _validate_file_paths({"other": ["relative/path.pdf"]})
        assert exc_info.value.status_code == 400
        assert "absolute" in exc_info.value.detail.lower()

    def test_traversal_path_rejected(self, tmp_path):
        from fastapi import HTTPException
        from uacragent.api.routes import _validate_file_paths

        with pytest.raises(HTTPException) as exc_info:
            _validate_file_paths({"other": ["../../etc/passwd"]})
        assert exc_info.value.status_code == 400
        assert "absolute" in exc_info.value.detail.lower()

    def test_nonexistent_file_rejected(self, tmp_path):
        from fastapi import HTTPException
        from uacragent.api.routes import _validate_file_paths

        with pytest.raises(HTTPException) as exc_info:
            _validate_file_paths({"other": [str(tmp_path / "no_such.pdf")]})
        assert exc_info.value.status_code == 400
        assert "not found" in exc_info.value.detail.lower()

    def test_directory_path_rejected(self, tmp_path):
        from fastapi import HTTPException
        from uacragent.api.routes import _validate_file_paths

        with pytest.raises(HTTPException) as exc_info:
            _validate_file_paths({"other": [str(tmp_path)]})
        assert exc_info.value.status_code == 400
        assert "not a regular file" in exc_info.value.detail.lower()

    def test_valid_absolute_file_accepted(self, tmp_path):
        from uacragent.api.routes import _validate_file_paths

        f = tmp_path / "notes.pdf"
        f.write_bytes(b"%PDF-1.4")
        _validate_file_paths({"other": [str(f)]})  # must not raise

    def test_allowed_base_dir_rejects_outside(self, tmp_path):
        from fastapi import HTTPException
        from uacragent.api.routes import _validate_file_paths

        outside = tmp_path / "outside.txt"
        outside.write_text("data")
        allowed = tmp_path / "allowed"
        allowed.mkdir()

        with patch.dict(os.environ, {"UACRAGENT_ALLOWED_BASE_DIR": str(allowed)}):
            with pytest.raises(HTTPException) as exc_info:
                _validate_file_paths({"other": [str(outside)]})
        assert exc_info.value.status_code == 400
        assert "outside" in exc_info.value.detail.lower()

    def test_allowed_base_dir_accepts_inside(self, tmp_path):
        from uacragent.api.routes import _validate_file_paths

        allowed = tmp_path / "allowed"
        allowed.mkdir()
        f = allowed / "notes.txt"
        f.write_text("content")

        with patch.dict(os.environ, {"UACRAGENT_ALLOWED_BASE_DIR": str(allowed)}):
            _validate_file_paths({"other": [str(f)]})  # must not raise

    def test_empty_classified_dict_passes(self):
        from uacragent.api.routes import _validate_file_paths
        _validate_file_paths({})  # must not raise

    def test_empty_file_list_passes(self, tmp_path):
        from uacragent.api.routes import _validate_file_paths
        _validate_file_paths({"other": []})  # must not raise


# ---------------------------------------------------------------------------
# POST /review — no-file request returns 400
# ---------------------------------------------------------------------------

def test_review_empty_files_returns_400(client):
    resp = client.post("/review", json={
        "classified_files": {},
        "course_name": "CS101",
    })
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Error handler mappings
# ---------------------------------------------------------------------------

class TestErrorHandlers:
    def test_llm_error_429_on_rate_limit(self, client):
        from uacragent.domain.errors import LLMError
        from uacragent.api.deps import invalidate_agent_service

        invalidate_agent_service()
        mock_service = MagicMock()
        mock_service.run_end_to_end.side_effect = LLMError("429 rate limit exceeded")

        with patch("uacragent.api.routes.get_agent_service", return_value=mock_service):
            resp = client.post("/review", json={
                "classified_files": {"other": ["/fake/file.pdf"]},
                "course_name": "CS101",
            })
        # Path validation fires first (file doesn't exist) → 400
        assert resp.status_code == 400

    def test_uacragent_error_returns_400(self, client):
        """UACRAgentError (base) is handled and returns 400."""
        from uacragent.api.main import create_app
        from uacragent.domain.errors import UACRAgentError
        app = create_app()
        from fastapi import Request
        from fastapi.testclient import TestClient

        @app.get("/raise-uacragent-error")
        def _raise():
            raise UACRAgentError("something went wrong")

        with TestClient(app, raise_server_exceptions=False) as tc:
            resp = tc.get("/raise-uacragent-error")
        assert resp.status_code == 400
        assert "something went wrong" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# deps.py — agent service singleton
# ---------------------------------------------------------------------------

class TestDeps:
    def test_get_agent_service_returns_same_instance(self):
        from uacragent.api.deps import get_agent_service, invalidate_agent_service

        invalidate_agent_service()
        with patch("uacragent.api.deps.AgentService") as mock_cls:
            mock_cls.return_value = MagicMock()
            svc1 = get_agent_service()
            svc2 = get_agent_service()
        assert svc1 is svc2

    def test_invalidate_forces_new_instance(self):
        from uacragent.api.deps import get_agent_service, invalidate_agent_service

        invalidate_agent_service()
        with patch("uacragent.api.deps.AgentService") as mock_cls:
            mock_cls.side_effect = [MagicMock(), MagicMock()]
            svc1 = get_agent_service()
            invalidate_agent_service()
            svc2 = get_agent_service()
        assert svc1 is not svc2
