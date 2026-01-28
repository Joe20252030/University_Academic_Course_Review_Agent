from __future__ import annotations

from pydantic import BaseModel, Field

class SectionSpec(BaseModel):
    title: str
    key_topics: list[str] = Field(..., min_length=1)
    importance: int = Field(..., ge=1, le=5)

class ReviewPlan(BaseModel):
    course_title: str
    exam_format: str
    sections: list[SectionSpec] = Field(..., min_length=1)