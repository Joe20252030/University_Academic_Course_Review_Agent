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


# Default test fixture shipped with the repo
TEST_FILE_PATHS = [
    "test_materials/outlines/MGTA01 Course Outline - MShibaeva (Fall 2025) - updated.pdf"
]


def main(
    classified_files: dict[DocumentType, list[str]],
    user_prefs: dict,
) -> None:
    """Run the generation pipeline with classified files.

    Args:
        classified_files: Files organized by document type.
        user_prefs: User preferences. Keys:
            course_name (required), exam_format, exam_type, task_type,
            extra_instructions, workspace_id, university_name, major,
            course_code, professor_name, semester.
    """
    service = AgentService()
    result = service.run_end_to_end(
        classified_files=classified_files,
        exam_format=str(user_prefs.get("exam_format", "unknown")),
        course_name=str(user_prefs.get("course_name", "")),
        exam_type=str(user_prefs.get("exam_type", "other")),
        task_type=str(user_prefs.get("task_type", "review_summary")),
        extra_instructions=str(user_prefs.get("extra_instructions", "")),
        workspace_id=str(user_prefs.get("workspace_id", "default")),
        university_name=str(user_prefs.get("university_name", "")),
        major=str(user_prefs.get("major", "")),
        course_code=str(user_prefs.get("course_code", "")),
        professor_name=str(user_prefs.get("professor_name", "")),
        semester=str(user_prefs.get("semester", "")),
    )
    print(f"Output generated at {result.markdown_path}")


def main_simple(file_paths: list[str], user_prefs: dict) -> None:
    """Simplified run that treats all files as 'other' type.

    Args:
        file_paths: List of file paths to process.
        user_prefs: Same keys as main().
    """
    service = AgentService()
    result = service.run_simple(
        file_paths=file_paths,
        exam_format=str(user_prefs.get("exam_format", "unknown")),
        course_name=str(user_prefs.get("course_name", "")),
        exam_type=str(user_prefs.get("exam_type", "other")),
        task_type=str(user_prefs.get("task_type", "review_summary")),
        extra_instructions=str(user_prefs.get("extra_instructions", "")),
        workspace_id=str(user_prefs.get("workspace_id", "default")),
        university_name=str(user_prefs.get("university_name", "")),
        major=str(user_prefs.get("major", "")),
        course_code=str(user_prefs.get("course_code", "")),
        professor_name=str(user_prefs.get("professor_name", "")),
        semester=str(user_prefs.get("semester", "")),
    )
    print(f"Output generated at {result.markdown_path}")


if __name__ == "__main__":
    load_dotenv()
    try:
        classified = {
            DocumentType.syllabus: TEST_FILE_PATHS,
        }
        main(
            classified,
            {
                "course_name": "MGTA01 - Introduction to Business",
                "exam_format": "written",
                "exam_type": "final",
                "task_type": "review_summary",
            },
        )
    except UACRAgentError as exc:
        raise SystemExit(f"Error: {exc}")
