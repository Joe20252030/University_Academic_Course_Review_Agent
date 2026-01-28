from __future__ import annotations

from dataclasses import dataclass

from uacragent.agent.pipeline import AgentPipeline
from uacragent.domain.models import ReviewPlan
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
        file_paths: list[str],
        exam_format: str,
        workspace_id: str = "default",
    ) -> ReviewResult:
        plan, markdown, markdown_path = self.pipeline.run_end_to_end(
            file_paths=file_paths,
            exam_format=exam_format,
            workspace_id=workspace_id,
        )
        return ReviewResult(plan=plan, markdown=markdown, markdown_path=markdown_path)
