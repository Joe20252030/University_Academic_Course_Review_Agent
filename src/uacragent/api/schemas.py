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
    """Request to generate course material."""
    classified_files: ClassifiedFiles = Field(...)
    course_name: str = Field(..., min_length=1, description="Full course name (required)")
    exam_format: ExamFormat = ExamFormat.written
    exam_type: ExamType = ExamType.other
    task_type: TaskType = TaskType.review_summary
    extra_instructions: str = ""
    workspace_id: str = "default"
    copy_to_workspace: bool = True
    # Optional course information
    university_name: str = ""
    major: str = ""
    course_code: str = ""
    professor_name: str = ""
    semester: str = ""
    # Optional exam details
    exam_duration: str = ""
    exam_info: str = ""


class SimpleReviewRequest(BaseModel):
    """Simplified request (backward compatible) - all files treated as 'other'."""
    file_paths: list[str] = Field(..., min_length=1)
    course_name: str = Field(..., min_length=1, description="Full course name (required)")
    exam_format: ExamFormat = ExamFormat.written
    exam_type: ExamType = ExamType.other
    task_type: TaskType = TaskType.review_summary
    extra_instructions: str = ""
    workspace_id: str = "default"
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
