from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

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
    """Generate a review from classified documents."""
    if req.classified_files.is_empty():
        raise HTTPException(status_code=400, detail="No files provided")

    result = service.run_end_to_end(
        classified_files=req.classified_files.to_dict(),
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

