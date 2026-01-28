from __future__ import annotations

import argparse

from uacragent.agent.service import AgentService
from uacragent.domain.errors import UACRAgentError


def _cli(args: argparse.Namespace) -> None:
    service = AgentService()
    try:
        result = service.run_end_to_end(
            file_paths=list(args.paths),
            exam_format=args.exam_format,
            workspace_id=args.workspace_id,
        )
        print(result.markdown_path)
    except UACRAgentError as exc:
        raise SystemExit(f"Error: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="UACRAgent: generate exam review from course outline")
    parser.add_argument("paths", nargs="*", help="Outline file paths (.pdf/.txt/.md)")
    parser.add_argument("--exam-format", default="written", help="Exam format hint")
    parser.add_argument("--workspace-id", default="default", help="Workspace ID under WORKSPACE_ROOT")
    parser.add_argument("--gui", action="store_true", help="Launch the desktop GUI instead of CLI")
    args = parser.parse_args()

    if args.gui or not args.paths:
        from uacragent.ui.desktop.app import main as gui_main
        gui_main()
    else:
        _cli(args)


if __name__ == "__main__":
    main()
