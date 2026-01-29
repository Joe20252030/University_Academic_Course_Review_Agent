from __future__ import annotations

from pydantic import BaseModel, Field

from uacragent.domain.models import ReviewPlan
from uacragent.domain.types import DocumentType


class ClassifiedFiles(BaseModel):
    """Files classified by document type."""
    syllabus: list[str] = Field(default_factory=list)
    lecture_note: list[str] = Field(default_factory=list)
    textbook: list[str] = Field(default_factory=list)
    assignment: list[str] = Field(default_factory=list)
    past_exam: list[str] = Field(default_factory=list)
    other: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[DocumentType, list[str]]:
        """Convert to dict[DocumentType, list[str]] format."""
        result: dict[DocumentType, list[str]] = {}
        if self.syllabus:
            result[DocumentType.syllabus] = self.syllabus
        if self.lecture_note:
            result[DocumentType.lecture_note] = self.lecture_note
        if self.textbook:
            result[DocumentType.textbook] = self.textbook
        if self.assignment:
            result[DocumentType.assignment] = self.assignment
        if self.past_exam:
            result[DocumentType.past_exam] = self.past_exam
        if self.other:
            result[DocumentType.other] = self.other
        return result

    def is_empty(self) -> bool:
        """Check if no files are provided."""
        return not any([
            self.syllabus, self.lecture_note, self.textbook,
            self.assignment, self.past_exam, self.other
        ])


class ReviewRequest(BaseModel):
    """Request to generate a course review."""
    classified_files: ClassifiedFiles = Field(...)
    exam_format: str = "written"
    workspace_id: str = "default"
    copy_to_workspace: bool = True


class SimpleReviewRequest(BaseModel):
    """Simplified request (backward compatible) - all files treated as 'other'."""
    file_paths: list[str] = Field(..., min_length=1)
    exam_format: str = "written"
    workspace_id: str = "default"


class ReviewResponse(BaseModel):
    """Response from review generation."""
    markdown_path: str
    plan: ReviewPlan
