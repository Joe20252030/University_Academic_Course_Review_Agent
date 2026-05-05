from __future__ import annotations

from dataclasses import dataclass

from uacragent.agent.pipeline import AgentPipeline
from uacragent.domain.models import ReviewPlan
from uacragent.domain.types import DocumentType
from uacragent.infra.settings import Settings, get_settings


@dataclass(frozen=True)
class ReviewResult:
    plan: ReviewPlan
    markdown: str
    markdown_path: str


class AgentService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings: Settings = settings or get_settings()
        self.pipeline = AgentPipeline(self.settings)

    def run_end_to_end(
        self,
        classified_files: dict[DocumentType, list[str]],
        exam_format: str,
        exam_type: str = "other",
        task_type: str = "review_summary",
        extra_instructions: str = "",
        workspace_id: str = "default",
        copy_to_workspace: bool = True,
    ) -> ReviewResult:
        """Run the generation pipeline with classified documents.

        Args:
            classified_files: Mapping of DocumentType to list of file paths
            exam_format: The exam format (written, mcq, mixed, unknown)
            exam_type: The exam type (quiz, midterm, final, term_test, other)
            task_type: What to generate (review_summary, practice_booklet,
                       mock_exam, exam_prediction)
            extra_instructions: Optional extra instructions from the user
            workspace_id: Workspace identifier
            copy_to_workspace: Whether to copy files to workspace folders

        Returns:
            ReviewResult with plan, markdown content, and output path
        """
        plan, markdown, markdown_path = self.pipeline.run_end_to_end(
            classified_files=classified_files,
            exam_format=exam_format,
            exam_type=exam_type,
            task_type=task_type,
            extra_instructions=extra_instructions,
            workspace_id=workspace_id,
            copy_to_workspace=copy_to_workspace,
        )
        return ReviewResult(plan=plan, markdown=markdown, markdown_path=markdown_path)

    def run_simple(
        self,
        file_paths: list[str],
        exam_format: str,
        exam_type: str = "other",
        task_type: str = "review_summary",
        extra_instructions: str = "",
        workspace_id: str = "default",
    ) -> ReviewResult:
        """Simplified interface that treats all files as 'other' type."""
        plan, markdown, markdown_path = self.pipeline.run_simple(
            file_paths=file_paths,
            exam_format=exam_format,
            exam_type=exam_type,
            task_type=task_type,
            extra_instructions=extra_instructions,
            workspace_id=workspace_id,
        )
        return ReviewResult(plan=plan, markdown=markdown, markdown_path=markdown_path)
