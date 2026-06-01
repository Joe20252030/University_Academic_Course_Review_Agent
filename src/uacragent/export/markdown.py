from __future__ import annotations

from pathlib import Path

from uacragent.export._utils import safe_timestamp
from uacragent.infra.workspace import WorkspacePaths


def save_markdown(md_text: str, workspace_paths: WorkspacePaths) -> str:
    from uacragent.domain.errors import ExportError
    try:
        Path(workspace_paths.outputs).mkdir(parents=True, exist_ok=True)
        path = Path(workspace_paths.outputs) / f"review_{safe_timestamp()}.md"
        path.write_text(md_text, encoding="utf-8")
        return str(path)
    except OSError as exc:
        raise ExportError(
            f"Could not save Markdown file: {exc}. "
            "Check that the workspace folder is writable and has enough disk space."
        ) from exc
