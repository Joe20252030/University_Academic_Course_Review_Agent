from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

# Ensure src/ is on sys.path so the package is importable
# even without `pip install -e .`.
ROOT = Path(__file__).resolve().parent
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from uacragent.agent.service import AgentService
from uacragent.domain.errors import UACRAgentError
from uacragent.domain.types import DocumentType


FILE_PATHS = ["data/default/uploads/outline.pdf"]
TEST_FILE_PATHS = [
    "tests/outlines/MGTA01 Course Outline - MShibaeva (Fall 2025) - updated.pdf"
]


def main(classified_files: dict[DocumentType, list[str]], user_prefs: dict) -> None:
    """Run the generation pipeline.

    Args:
        classified_files: Files organized by document type
        user_prefs: User preferences including:
            exam_format, exam_type, task_type, extra_instructions, workspace_id
    """
    service = AgentService()
    result = service.run_end_to_end(
        classified_files=classified_files,
        exam_format=str(user_prefs.get("exam_format", "unknown")),
        exam_type=str(user_prefs.get("exam_type", "other")),
        task_type=str(user_prefs.get("task_type", "review_summary")),
        extra_instructions=str(user_prefs.get("extra_instructions", "")),
        workspace_id=str(user_prefs.get("workspace_id", "default")),
    )
    print(f"Output generated at {result.markdown_path}")


def main_simple(file_paths: list[str], user_prefs: dict) -> None:
    """Simplified run that treats all files as 'other' type."""
    service = AgentService()
    result = service.run_simple(
        file_paths=file_paths,
        exam_format=str(user_prefs.get("exam_format", "unknown")),
        exam_type=str(user_prefs.get("exam_type", "other")),
        task_type=str(user_prefs.get("task_type", "review_summary")),
        extra_instructions=str(user_prefs.get("extra_instructions", "")),
        workspace_id=str(user_prefs.get("workspace_id", "default")),
    )
    print(f"Output generated at {result.markdown_path}")


if __name__ == "__main__":
    load_dotenv()
    try:
        classified = {
            DocumentType.syllabus: TEST_FILE_PATHS,
        }
        main(classified, {"exam_format": "written", "exam_type": "final", "task_type": "review_summary"})
    except UACRAgentError as exc:
        raise SystemExit(f"Error: {exc}")
