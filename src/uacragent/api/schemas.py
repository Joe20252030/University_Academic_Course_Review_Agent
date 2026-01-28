from __future__ import annotations

from pydantic import BaseModel, Field

from uacragent.domain.models import ReviewPlan


class ReviewRequest(BaseModel):
    file_paths: list[str] = Field(..., min_length=1)
    exam_format: str = "written"
    workspace_id: str = "default"


class ReviewResponse(BaseModel):
    markdown_path: str
    plan: ReviewPlan
