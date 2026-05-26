"""UACRAgent — command-line entry point.

Usage
-----
Desktop GUI (default when no file paths are given):
    python -m uacragent [--gui]

Interactive conversational CLI:
    python -m uacragent lecture1.pdf lecture2.pdf \\
        --course-name "Introduction to Algorithms" \\
        [--doc-type lecture_note] \\
        [--exam-type final] \\
        [--exam-format written] \\
        [--workspace-id my-algo-session]

The CLI indexes the supplied documents once and then enters a chat loop.
Ask any question, or request a study document:
    "Generate a review summary for this course."
    "Generate a practice booklet for this course."
    "Generate a mock exam for this course."
    "Generate an exam prediction for this course."

Type  exit  or press Ctrl-C / Ctrl-D to quit.

LLM provider, model, and API keys are read from environment variables or a
.env file in the working directory (same as the desktop mode):
    LLM_PROVIDER       gemini | openai | deepseek  (default: gemini)
    LLM_MODEL          e.g. gemini-2.5-flash
    GOOGLE_API_KEY     / OPENAI_API_KEY / DEEPSEEK_API_KEY
    EMBEDDING_PROVIDER gemini | openai | local      (default: gemini)
"""
from __future__ import annotations

import argparse
import sys

from uacragent.domain.errors import UACRAgentError
from uacragent.domain.types import DocumentType, ExamType


# ---------------------------------------------------------------------------
# CLI progress helper
# ---------------------------------------------------------------------------

def _make_cli_progress():
    """Return (progress_cb, finish_cb) for live single-line status in the terminal.

    In a real TTY the status line is overwritten in-place with \\r so the
    terminal stays clean.  When stdout is redirected (pipe / file) each step
    is emitted on its own line instead.
    """
    is_tty = sys.stdout.isatty()
    _last_len: list[int] = [0]

    def progress_cb(msg: str) -> None:
        line = f"  ⋯ {msg}"
        if is_tty:
            # Overwrite previous status line
            clear = " " * _last_len[0]
            print(f"\r{clear}\r{line}", end="", flush=True)
            _last_len[0] = len(line)
        else:
            print(line, flush=True)

    def finish_cb() -> None:
        """Advance past the overwritten status line."""
        if is_tty and _last_len[0]:
            print()          # move to next line
            _last_len[0] = 0

    return progress_cb, finish_cb


# ---------------------------------------------------------------------------
# Conversational CLI
# ---------------------------------------------------------------------------

def _cli(args: argparse.Namespace) -> None:
    """Index documents (if any) then run an interactive chat loop."""

    if not args.course_name:
        raise SystemExit("error: --course-name is required for the CLI")

    # ── Startup: must run before any HuggingFace / sentence-transformers import
    from dotenv import load_dotenv
    from uacragent.infra.persistence import configure_hf_cache, get_app_data_dir
    _app_env = get_app_data_dir() / ".env"
    if _app_env.exists():
        load_dotenv(_app_env)
    load_dotenv()   # cwd fallback; won't override keys already loaded above
    configure_hf_cache()

    from uacragent.agent.conversation import ConversationAgent
    from uacragent.agent.session import AgentSession
    from uacragent.infra.settings import get_settings

    # ── Build classified file set ─────────────────────────────────────────────
    classified_files: dict[DocumentType, list[str]] = {}
    if args.paths:
        if args.doc_type:
            try:
                doc_type = DocumentType(args.doc_type)
            except ValueError:
                valid = ", ".join(dt.value for dt in DocumentType)
                raise SystemExit(
                    f"Invalid --doc-type '{args.doc_type}'.  Valid values: {valid}"
                )
            classified_files[doc_type] = list(args.paths)
        else:
            # No explicit type → treat all as 'other'; user can pass --doc-type
            # when all files belong to the same category.
            classified_files[DocumentType.other] = list(args.paths)

    # ── Build session ─────────────────────────────────────────────────────────
    settings = get_settings()
    session = AgentSession(
        course_name=args.course_name,
        university_name=args.university_name or "",
        major=args.major or "",
        course_code=args.course_code or "",
        professor_name=args.professor_name or "",
        semester=args.semester or "",
        exam_type=args.exam_type,
        exam_format=args.exam_format,
        exam_duration=args.exam_duration or "",
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        workspace_id=args.workspace_id,
        extra_instructions=args.extra_instructions or "",
        classified_files=classified_files,
    )

    agent = ConversationAgent(settings)

    # ── Header ────────────────────────────────────────────────────────────────
    W = 64
    print(f"\n{'═' * W}")
    title = f"  UACRAgent  ·  {args.course_name}"
    if args.exam_type and args.exam_type != "other":
        title += f"  [{args.exam_type}]"
    print(title)
    print(f"{'═' * W}")
    print(f"  Provider  : {settings.llm_provider} / {settings.llm_model}")
    print(f"  Embedding : {settings.embedding_provider}")
    if classified_files:
        n_files = sum(len(v) for v in classified_files.values())
        types   = ", ".join(dt.value for dt in classified_files)
        print(f"  Files     : {n_files} file(s)  ({types})")
    else:
        print("  Files     : none — answers will use general knowledge only")
    print(f"{'─' * W}\n")

    # ── Index documents ───────────────────────────────────────────────────────
    if classified_files:
        print("Indexing documents…")
    _progress, _finish = _make_cli_progress()
    status, _ = agent.initialize_session(session, progress_cb=_progress if classified_files else None)
    _finish()
    print(f"✓  {status}\n")

    # ── Usage hint ────────────────────────────────────────────────────────────
    print(f"{'─' * W}")
    print("  Ask any question about the course, or use a quick action:")
    print("    • Generate a review summary for this course.")
    print("    • Generate a practice booklet for this course.")
    print("    • Generate a mock exam for this course.")
    print("    • Generate an exam prediction for this course.")
    print(f'  Type "exit" or press Ctrl-C / Ctrl-D to quit.')
    print(f"{'─' * W}\n")

    # ── readline: history + line-editing on Unix / macOS ─────────────────────
    try:
        import readline          # noqa: F401 — imported for its side-effects
        readline.set_history_length(200)
    except ImportError:
        pass                     # Windows: no readline; input() still works

    # ── Chat loop ─────────────────────────────────────────────────────────────
    while True:
        try:
            user_input = input("You: ").strip()
        except KeyboardInterrupt:
            print("\n\nInterrupted.  Goodbye!")
            break
        except EOFError:
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit", "q", ":q"):
            print("Goodbye!")
            break

        _progress, _finish = _make_cli_progress()
        try:
            response = agent.chat(
                user_input, session,
                progress_cb=_progress,
                effort_level=args.effort_level,
            )
        except Exception as exc:          # noqa: BLE001
            _finish()
            print(f"\n⚠  Error: {exc}\n")
            continue
        _finish()

        print(f"\nAssistant:\n{response.text}")

        if response.output_path:
            print(f"\n📄  Document saved to: {response.output_path}")

        if response.error:
            print(f"\n⚠  {response.error}")

        print()


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m uacragent",
        description=(
            "UACRAgent: index course documents and chat with an AI tutor.\n"
            "Omit file paths (or pass --gui) to open the desktop GUI instead."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Positional: zero or more file paths
    parser.add_argument(
        "paths",
        nargs="*",
        metavar="FILE",
        help="Course document files (.pdf / .txt / .md / .docx)",
    )

    # Document classification
    parser.add_argument(
        "--doc-type",
        choices=[dt.value for dt in DocumentType],
        metavar="TYPE",
        help=(
            "Document type applied to all input files: "
            + ", ".join(dt.value for dt in DocumentType)
        ),
    )

    # Course information
    parser.add_argument(
        "--course-name",
        default="",
        metavar="NAME",
        help="Full course name, e.g. 'Introduction to Algorithms'  (required)",
    )
    parser.add_argument("--university-name", default="", metavar="NAME")
    parser.add_argument("--major",           default="", metavar="DEPT",
                        help="Department / field of study, e.g. 'Computer Science'")
    parser.add_argument("--course-code",     default="", metavar="CODE",
                        help="Course code, e.g. CS101")
    parser.add_argument("--professor-name",  default="", metavar="NAME")
    parser.add_argument("--semester",        default="", metavar="TERM",
                        help="e.g. 'Fall 2024'")

    # Exam options
    parser.add_argument(
        "--exam-type",
        choices=[et.value for et in ExamType],
        default="other",
        metavar="TYPE",
        help="quiz | midterm | final | term_test | other  (default: other)",
    )
    parser.add_argument(
        "--exam-format",
        default="written",
        metavar="FORMAT",
        help="written | mcq | mixed | unknown  (default: written)",
    )
    parser.add_argument(
        "--exam-duration",
        default="",
        metavar="DURATION",
        help="e.g. '2 hours' or '90 minutes'",
    )

    # Misc
    parser.add_argument(
        "--extra-instructions",
        default="",
        metavar="TEXT",
        help="Additional instructions passed to the LLM for every request",
    )
    parser.add_argument(
        "--effort-level",
        choices=["low", "medium", "high"],
        default="medium",
        metavar="LEVEL",
        help="Retrieval depth for each chat turn: low | medium | high  (default: medium)",
    )
    parser.add_argument(
        "--workspace-id",
        default="default",
        metavar="ID",
        help=(
            "Identifier for the workspace folder used to store the vector store "
            "and outputs.  Reuse the same ID across runs to skip re-embedding "
            "unchanged files."
        ),
    )

    # GUI override
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the desktop GUI regardless of other arguments",
    )

    args = parser.parse_args()

    # Desktop mode: no file paths provided, or --gui flag
    if args.gui or not args.paths:
        from uacragent.ui.desktop.app import main as gui_main
        gui_main()
        return

    # Conversational CLI mode
    try:
        _cli(args)
    except UACRAgentError as exc:
        raise SystemExit(f"Error: {exc}")


if __name__ == "__main__":
    main()
