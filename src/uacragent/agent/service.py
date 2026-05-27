from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

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

    def run_simple(
        self,
        file_paths: list[str],
        exam_format: str,
        course_name: str,
        exam_type: str = "other",
        task_type: str = "review_summary",
        extra_instructions: str = "",
        workspace_id: str = "default",
        copy_to_workspace: bool = True,
        university_name: str = "",
        major: str = "",
        course_code: str = "",
        professor_name: str = "",
        semester: str = "",
        exam_duration: str = "",
        exam_info: str = "",
        workspace_folder: Path | None = None,
        progress_cb: Callable[[str], None] | None = None,
        effort_level: str = "medium",
        reasoning_mode: str = "quick",
    ) -> ReviewResult:
        """Unclassified wrapper — treats every input file as ``DocumentType.other``.

        .. deprecated::
            Prefer :meth:`run_end_to_end` with an explicit ``classified_files``
            mapping so that doc-type-aware retrieval and per-type chunking
            strategies are applied correctly.  This method is kept for backward
            compatibility with simple scripts that do not classify their files.
        """
        return self.run_end_to_end(
            classified_files={DocumentType.other: list(file_paths)},
            exam_format=exam_format,
            course_name=course_name,
            exam_type=exam_type,
            task_type=task_type,
            extra_instructions=extra_instructions,
            workspace_id=workspace_id,
            copy_to_workspace=copy_to_workspace,
            university_name=university_name,
            major=major,
            course_code=course_code,
            professor_name=professor_name,
            semester=semester,
            exam_duration=exam_duration,
            exam_info=exam_info,
            workspace_folder=workspace_folder,
            progress_cb=progress_cb,
            effort_level=effort_level,
            reasoning_mode=reasoning_mode,
        )

    def run_end_to_end(
        self,
        classified_files: dict[DocumentType, list[str]],
        exam_format: str,
        course_name: str,
        exam_type: str = "other",
        task_type: str = "review_summary",
        extra_instructions: str = "",
        workspace_id: str = "default",
        copy_to_workspace: bool = True,
        university_name: str = "",
        major: str = "",
        course_code: str = "",
        professor_name: str = "",
        semester: str = "",
        exam_duration: str = "",
        exam_info: str = "",
        workspace_folder: Path | None = None,
        progress_cb: Callable[[str], None] | None = None,
        effort_level: str = "medium",
        reasoning_mode: str = "quick",
    ) -> ReviewResult:
        plan, markdown, markdown_path = self.pipeline.run_end_to_end(
            classified_files=classified_files,
            exam_format=exam_format,
            course_name=course_name,
            exam_type=exam_type,
            task_type=task_type,
            extra_instructions=extra_instructions,
            workspace_id=workspace_id,
            copy_to_workspace=copy_to_workspace,
            university_name=university_name,
            major=major,
            course_code=course_code,
            professor_name=professor_name,
            semester=semester,
            exam_duration=exam_duration,
            exam_info=exam_info,
            workspace_folder=workspace_folder,
            progress_cb=progress_cb,
            effort_level=effort_level,
            reasoning_mode=reasoning_mode,
        )
        return ReviewResult(plan=plan, markdown=markdown, markdown_path=markdown_path)
