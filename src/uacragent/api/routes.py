"""API routes for UACRAgent.

SECURITY NOTE: This API does not restrict file paths by default.  For any
non-local deployment, set the UACRAGENT_ALLOWED_BASE_DIR environment variable
to restrict file access to a trusted directory.  Without this variable set,
the API accepts any absolute path that exists on the host filesystem, which is
a path-traversal risk in multi-tenant or network-exposed environments.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from uacragent.agent.service import AgentService
from uacragent.api.deps import get_agent_service
from uacragent.api.schemas import ReviewRequest, ReviewResponse
from uacragent.infra.persistence import get_api_run_dir


router = APIRouter()


# ---------------------------------------------------------------------------
# Path-traversal guard
# ---------------------------------------------------------------------------
# SECURITY NOTE: When UACRAGENT_ALLOWED_BASE_DIR is set, every file path in an
# API request must resolve under that directory, preventing path-traversal
# attacks.  When unset, the API still requires absolute existing regular files
# but does not restrict requests to a single root directory — do NOT expose
# this API publicly without setting UACRAGENT_ALLOWED_BASE_DIR.
#
# The env var is read per-request (not at import time) so that:
# - Integration tests that set the variable after module import are respected.
# - Hot-reload scenarios where the variable changes between requests work.

def _get_allowed_base_dir() -> "Path | None":
    """Return the resolved allowed base directory, or None if unset."""
    raw = os.environ.get("UACRAGENT_ALLOWED_BASE_DIR", "").strip()
    return Path(raw).resolve() if raw else None


def _validate_file_paths(classified_files_dict: dict) -> None:
    """Raise HTTP 400 if any file path is unsafe.

    Checks performed:
    1. Path must be absolute (relative paths are ambiguous and risky).
    2. If ``UACRAGENT_ALLOWED_BASE_DIR`` is configured, the resolved path must
       be inside that directory tree.
    3. The file must exist on disk (avoids ingest errors deeper in the stack).
    4. The path must refer to a regular file.

    Raises
    ------
    HTTPException(400)
        With a descriptive message for the first failing path found.
    """
    allowed_base_dir = _get_allowed_base_dir()

    for paths in classified_files_dict.values():
        for raw_path in paths:
            # Check that the raw input is already absolute *before* resolve(),
            # because Path.resolve() always returns an absolute path regardless
            # of what the input was — checking is_absolute() after resolve()
            # would be dead code and would never reject relative paths.
            if not Path(raw_path).is_absolute():
                raise HTTPException(
                    status_code=400,
                    detail=f"File path must be absolute: '{raw_path}'",
                )

            try:
                p = Path(raw_path).resolve()
            except (ValueError, OSError) as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid file path '{raw_path}': {exc}",
                )

            if allowed_base_dir is not None:
                try:
                    p.relative_to(allowed_base_dir)
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"File path '{raw_path}' is outside the allowed "
                            f"base directory. Set UACRAGENT_ALLOWED_BASE_DIR "
                            f"to permit a different location."
                        ),
                    )

            if not p.exists():
                raise HTTPException(
                    status_code=400,
                    detail=f"File not found: '{raw_path}'",
                )

            if not p.is_file():
                raise HTTPException(
                    status_code=400,
                    detail=f"Path is not a regular file: '{raw_path}'",
                )


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/review", response_model=ReviewResponse)
def generate_review(
    req: ReviewRequest,
    service: AgentService = Depends(get_agent_service),
) -> ReviewResponse:
    """Generate a review from classified documents."""
    if req.classified_files.is_empty():
        raise HTTPException(status_code=400, detail="No files provided")

    classified = req.classified_files.to_dict()
    _validate_file_paths(classified)

    result = service.run_end_to_end(
        classified_files=classified,
        exam_format=req.exam_format.value,
        course_name=req.course_name,
        exam_type=req.exam_type.value,
        task_type=req.task_type.value,
        extra_instructions=req.extra_instructions,
        workspace_id=req.workspace_id,
        copy_to_workspace=req.copy_to_workspace,
        university_name=req.university_name,
        major=req.major,
        course_code=req.course_code,
        professor_name=req.professor_name,
        semester=req.semester,
        exam_duration=req.exam_duration,
        exam_info=req.exam_info,
        workspace_folder=(get_api_run_dir() / req.workspace_id).resolve(),
        effort_level=req.effort_level,
        reasoning_mode=req.reasoning_mode,
    )
    return ReviewResponse(markdown_path=result.markdown_path, plan=result.plan)
