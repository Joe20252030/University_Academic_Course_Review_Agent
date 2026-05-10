from __future__ import annotations

from pathlib import Path

from uacragent.export._utils import safe_timestamp
from uacragent.infra.workspace import WorkspacePaths


def save_markdown(md_text: str, work_space_paths: WorkspacePaths) -> str:
    Path(work_space_paths.outputs).mkdir(parents=True, exist_ok=True)
    path = Path(work_space_paths.outputs) / f"review_{safe_timestamp()}.md"
    path.write_text(md_text, encoding="utf-8")
    return str(path)
