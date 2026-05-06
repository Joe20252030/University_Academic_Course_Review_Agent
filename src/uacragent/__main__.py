from __future__ import annotations

import argparse

from uacragent.agent.service import AgentService
from uacragent.domain.errors import UACRAgentError
from uacragent.domain.types import DocumentType, ExamType, TaskType


def _cli(args: argparse.Namespace) -> None:
    """Run CLI with optional document type classification."""
    if not args.course_name:
        raise SystemExit("error: --course-name is required when running the CLI pipeline")

    service = AgentService()

    common_kwargs = dict(
        exam_format=args.exam_format,
        course_name=args.course_name,
        exam_type=args.exam_type,
        task_type=args.task_type,
        extra_instructions=args.extra_instructions or "",
        workspace_id=args.workspace_id,
        university_name=args.university_name or "",
        major=args.major or "",
        course_code=args.course_code or "",
        professor_name=args.professor_name or "",
        semester=args.semester or "",
        exam_duration=args.exam_duration or "",
        exam_info=args.exam_info or "",
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
    # Course information (course-name is required when running the CLI pipeline)
    parser.add_argument(
        "--course-name",
        default="",
        help="Full course name, e.g. 'Introduction to Algorithms' (required for CLI runs)",
    )
    parser.add_argument("--university-name", default="", help="University name (e.g. University of Toronto)")
    parser.add_argument("--major", default="", help="Major or department (e.g. Computer Science)")
    parser.add_argument("--course-code", default="", help="Course code (e.g. CS101)")
    parser.add_argument("--professor-name", default="", help="Professor name")
    parser.add_argument("--semester", default="", help="Semester/term (e.g. Fall 2024)")
    parser.add_argument("--exam-duration", default="", help="Exam duration (e.g. '2 hours', '90 minutes')")
    parser.add_argument("--exam-info", default="", help="Exam information sheet text (allowed materials, topics, rules, etc.)")
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
