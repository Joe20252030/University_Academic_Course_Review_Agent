from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from uacragent.agent.service import AgentService
from uacragent.api.deps import get_agent_service
from uacragent.api.schemas import ReviewRequest, SimpleReviewRequest, ReviewResponse


router = APIRouter()


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

    result = service.run_end_to_end(
        classified_files=req.classified_files.to_dict(),
        exam_format=req.exam_format,
        workspace_id=req.workspace_id,
        copy_to_workspace=req.copy_to_workspace,
    )
    return ReviewResponse(markdown_path=result.markdown_path, plan=result.plan)


@router.post("/review/simple", response_model=ReviewResponse)
def generate_review_simple(
    req: SimpleReviewRequest,
    service: AgentService = Depends(get_agent_service),
) -> ReviewResponse:
    """Generate a review using simple file list (backward compatible).

    All files are treated as 'other' document type.
    """
    result = service.run_simple(
        file_paths=req.file_paths,
        exam_format=req.exam_format,
        workspace_id=req.workspace_id,
    )
    return ReviewResponse(markdown_path=result.markdown_path, plan=result.plan)
