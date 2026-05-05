from __future__ import annotations

import argparse

from uacragent.agent.service import AgentService
from uacragent.domain.errors import UACRAgentError
from uacragent.domain.types import DocumentType, ExamType, TaskType


def _cli(args: argparse.Namespace) -> None:
    """Run CLI with optional document type classification."""
    service = AgentService()

    common_kwargs = dict(
        exam_format=args.exam_format,
        exam_type=args.exam_type,
        task_type=args.task_type,
        extra_instructions=args.extra_instructions or "",
        workspace_id=args.workspace_id,
    )

    if args.doc_type:
        try:
            doc_type = DocumentType(args.doc_type)
        except ValueError:
            valid = ", ".join(dt.value for dt in DocumentType)
            raise SystemExit(f"Invalid document type: {args.doc_type}. Valid types: {valid}")

        classified_files = {doc_type: list(args.paths)}
        result = service.run_end_to_end(
            classified_files=classified_files,
            **common_kwargs,
        )
    else:
        result = service.run_simple(
            file_paths=list(args.paths),
            **common_kwargs,
        )

    print(result.markdown_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="UACRAgent: generate exam review materials from course documents"
    )
    parser.add_argument("paths", nargs="*", help="File paths (.pdf/.txt/.md/.docx)")
    parser.add_argument("--exam-format", default="written", help="Exam format: written, mcq, mixed, unknown")
    parser.add_argument(
        "--exam-type",
        choices=[et.value for et in ExamType],
        default="other",
        help="Exam type: quiz, midterm, final, term_test, other",
    )
    parser.add_argument(
        "--task-type",
        choices=[tt.value for tt in TaskType],
        default="review_summary",
        help="Task: review_summary, practice_booklet, mock_exam, exam_prediction",
    )
    parser.add_argument("--extra-instructions", default="", help="Additional instructions for the LLM")
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
