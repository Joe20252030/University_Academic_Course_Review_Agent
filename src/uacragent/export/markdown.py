from __future__ import annotations

from datetime import datetime
from pathlib import Path

from uacragent.infra.workspace import WorkspacePaths


def _safe_timestamp() -> str:
    """Return a filename-safe timestamp (no colons, works on Windows)."""
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def save_markdown(md_text: str, work_space_paths: WorkspacePaths) -> str:
    Path(work_space_paths.outputs).mkdir(parents=True, exist_ok=True)
    path = Path(work_space_paths.outputs) / f"review_{_safe_timestamp()}.md"
    path.write_text(md_text, encoding="utf-8")
    return str(path)
