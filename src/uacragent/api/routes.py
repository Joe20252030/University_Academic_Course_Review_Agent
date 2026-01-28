from __future__ import annotations

from fastapi import APIRouter, Depends

from uacragent.agent.service import AgentService
from uacragent.api.deps import get_agent_service
from uacragent.api.schemas import ReviewRequest, ReviewResponse


router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/review", response_model=ReviewResponse)
def generate_review(
    req: ReviewRequest,
    service: AgentService = Depends(get_agent_service),
) -> ReviewResponse:
    result = service.run_end_to_end(
        file_paths=req.file_paths,
        exam_format=req.exam_format,
        workspace_id=req.workspace_id,
    )
    return ReviewResponse(markdown_path=result.markdown_path, plan=result.plan)