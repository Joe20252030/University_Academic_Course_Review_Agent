from __future__ import annotations

import argparse

from uacragent.agent.service import AgentService
from uacragent.domain.errors import UACRAgentError
from uacragent.domain.types import DocumentType


def _cli(args: argparse.Namespace) -> None:
    """Run CLI with optional document type classification."""
    service = AgentService()

    # If doc-type is specified, use classified mode; otherwise use simple mode
    if args.doc_type:
        try:
            doc_type = DocumentType(args.doc_type)
        except ValueError:
            valid = ", ".join(dt.value for dt in DocumentType)
            raise SystemExit(f"Invalid document type: {args.doc_type}. Valid types: {valid}")

        classified_files = {doc_type: list(args.paths)}
        result = service.run_end_to_end(
            classified_files=classified_files,
            exam_format=args.exam_format,
            workspace_id=args.workspace_id,
        )
    else:
        # Simple mode - treat all files as 'other'
        result = service.run_simple(
            file_paths=list(args.paths),
            exam_format=args.exam_format,
            workspace_id=args.workspace_id,
        )

    print(result.markdown_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="UACRAgent: generate exam review from course materials"
    )
    parser.add_argument("paths", nargs="*", help="File paths (.pdf/.txt/.md/.docx)")
    parser.add_argument("--exam-format", default="written", help="Exam format: written, mcq, mixed, unknown")
    parser.add_argument("--workspace-id", default="default", help="Workspace ID under WORKSPACE_ROOT")
    parser.add_argument(
        "--doc-type",
        choices=[dt.value for dt in DocumentType],
        help="Document type for all input files: syllabus, lecture_note, textbook, assignment, past_exam, other"
    )
    parser.add_argument("--gui", action="store_true", help="Launch the desktop GUI instead of CLI")
    args = parser.parse_args()

    if args.gui or not args.paths:
        from uacragent.ui.desktop.app import main as gui_main
        gui_main()
    else:
        try:
            _cli(args)
        except UACRAgentError as exc:
            raise SystemExit(f"Error: {exc}")


if __name__ == "__main__":
    main()
