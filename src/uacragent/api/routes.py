from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from uacragent.agent.service import AgentService
from uacragent.api.deps import get_agent_service
from uacragent.api.schemas import ReviewRequest, ReviewResponse


router = APIRouter()

# ---------------------------------------------------------------------------
# Path-traversal guard
# ---------------------------------------------------------------------------
# When set, every file path in an API request must resolve under this directory.
# Configure via the UACRAGENT_ALLOWED_BASE_DIR environment variable.
# When unset, the API still requires absolute existing regular files, but does
# not restrict requests to a single root directory.
_ALLOWED_BASE_DIR: Path | None = (
    Path(os.environ["UACRAGENT_ALLOWED_BASE_DIR"]).resolve()
    if "UACRAGENT_ALLOWED_BASE_DIR" in os.environ
    else None
)


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
    for paths in classified_files_dict.values():
        for raw_path in paths:
            try:
                p = Path(raw_path).resolve()
            except (ValueError, OSError) as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid file path '{raw_path}': {exc}",
                )

            if not p.is_absolute():
                raise HTTPException(
                    status_code=400,
                    detail=f"File path must be absolute: '{raw_path}'",
                )

            if _ALLOWED_BASE_DIR is not None:
                try:
                    p.relative_to(_ALLOWED_BASE_DIR)
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
        effort_level=req.effort_level,
    )
    return ReviewResponse(markdown_path=result.markdown_path, plan=result.plan)
