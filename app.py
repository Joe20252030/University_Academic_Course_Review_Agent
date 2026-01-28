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


FILE_PATHS = ["data/default/uploads/outline.pdf"]
TEST_FILE_PATHS = [
    "tests/outlines/MGTA01 Course Outline - MShibaeva (Fall 2025) - updated.pdf"
]


def main(file_paths: list[str], user_prefs: dict) -> None:
    service = AgentService()
    result = service.run_end_to_end(
        file_paths=file_paths,
        exam_format=str(user_prefs.get("exam_format", "unknown")),
        workspace_id=str(user_prefs.get("workspace_id", "default")),
    )
    print(f"Review generated at {result.markdown_path}")


if __name__ == "__main__":
    load_dotenv()
    try:
        main(TEST_FILE_PATHS, {"exam_format": "written"})
    except UACRAgentError as exc:
        raise SystemExit(f"Error: {exc}")
