from __future__ import annotations

from pydantic import BaseModel, Field

from uacragent.domain.models import ReviewPlan
from uacragent.domain.types import DocumentType, ExamFormat, ExamType, TaskType


class ClassifiedFiles(BaseModel):
    """Files classified by document type."""
    syllabus: list[str] = Field(default_factory=list)
    lecture_note: list[str] = Field(default_factory=list)
    textbook: list[str] = Field(default_factory=list)
    assignment: list[str] = Field(default_factory=list)
    past_exam: list[str] = Field(default_factory=list)
    other: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[DocumentType, list[str]]:
        """Convert to ``dict[DocumentType, list[str]]``, omitting empty buckets."""
        return {
            dt: files
            for dt in DocumentType
            if (files := getattr(self, dt.value, []))
        }

    def is_empty(self) -> bool:
        """Return True when no files are provided across all document types."""
        return not any(getattr(self, dt.value, []) for dt in DocumentType)


class ReviewRequest(BaseModel):
    """Request to generate course material."""
    classified_files: ClassifiedFiles = Field(...)
    course_name: str = Field(..., min_length=1, description="Full course name (required)")
    exam_format: ExamFormat = ExamFormat.written
    exam_type: ExamType = ExamType.other
    task_type: TaskType = TaskType.review_summary
    extra_instructions: str = ""
    workspace_id: str = "default"
    copy_to_workspace: bool = True
    # Retrieval / generation depth — controls how many chunks are retrieved
    # and how much of the corpus is sampled for plan generation.
    effort_level: str = Field(default="medium", pattern=r"^(low|medium|high)$")
    # Optional course information
    university_name: str = ""
    major: str = ""
    course_code: str = ""
    professor_name: str = ""
    semester: str = ""
    # Optional exam details
    exam_duration: str = ""
    exam_info: str = ""


class ReviewResponse(BaseModel):
    """Response from review generation."""
    markdown_path: str
    plan: ReviewPlan
