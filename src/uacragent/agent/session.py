"""AgentSession — all mutable state for one conversation session."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from langchain_core.messages import BaseMessage
from langchain_core.retrievers import BaseRetriever

from uacragent.domain.types import DocumentType


@dataclass
class AgentSession:
    """Holds everything that belongs to one user session.

    Attributes that are purely runtime (retriever, chat_history) live here
    alongside user-supplied settings so that every pipeline call has a single
    source of truth.
    """

    # ── Course information ─────────────────────────────────────────────────
    course_name: str = ""
    university_name: str = ""
    major: str = ""           # department / field of the course
    course_code: str = ""
    professor_name: str = ""
    semester: str = ""

    # ── Exam settings ─────────────────────────────────────────────────────
    exam_type: str = "final"
    exam_format: str = "written"
    exam_duration: str = ""
    exam_info_path: str = ""   # path to exam information sheet file

    # ── Model selection ───────────────────────────────────────────────────
    llm_provider: str = "gemini"       # gemini | openai | deepseek
    llm_model: str = "gemini-2.5-flash"

    # ── Misc ──────────────────────────────────────────────────────────────
    # Each new session gets a unique 12-char hex ID so its auto-created folder
    # inside the app data dir never collides with other sessions.
    workspace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    workspace_folder: Path | None = field(default=None)  # set once on first Apply; locked thereafter
    extra_instructions: str = ""

    # ── Files ─────────────────────────────────────────────────────────────
    classified_files: dict[DocumentType, list[str]] = field(default_factory=dict)

    # ── Runtime (not serialised) ───────────────────────────────────────────
    retriever: BaseRetriever | None = field(default=None, repr=False)
    chat_history: list[BaseMessage] = field(default_factory=list)

    # Cache for read_exam_info() — invalidated when exam_info_path changes.
    _exam_info_cache: tuple[str, str] | None = field(default=None, repr=False)

    # ── Helpers ───────────────────────────────────────────────────────────

    def has_files(self) -> bool:
        return any(paths for paths in self.classified_files.values())

    def active_files(self) -> dict[DocumentType, list[str]]:
        """Return only doc-type buckets that have at least one file."""
        return {k: v for k, v in self.classified_files.items() if v}

    def read_exam_info(self) -> str:
        """Read and return the content of the exam info sheet file, or ''.

        The result is cached so that repeated calls within a single session
        (e.g. one per chat turn) do not repeat expensive PDF/docx parsing.
        The cache is invalidated automatically when *exam_info_path* changes.
        """
        path = self.exam_info_path
        if not path:
            return ""
        # Return cached value if the path hasn't changed since last read.
        if self._exam_info_cache is not None and self._exam_info_cache[0] == path:
            return self._exam_info_cache[1]
        try:
            p = Path(path)
            suffix = p.suffix.lower()
            if suffix == ".pdf":
                from langchain_community.document_loaders import PyPDFLoader
                docs = PyPDFLoader(path).load()
                content = "\n".join(d.page_content for d in docs).strip()
            elif suffix == ".docx":
                import docx2txt
                content = docx2txt.process(path).strip()
            else:
                content = p.read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            content = ""
        self._exam_info_cache = (path, content)
        return content

    def to_user_prefs(self) -> dict:
        """Build the user_prefs dict expected by the pipeline."""
        return {
            "course_name": self.course_name,
            "university_name": self.university_name,
            "major": self.major,
            "course_code": self.course_code,
            "professor_name": self.professor_name,
            "semester": self.semester,
            "exam_type": self.exam_type,
            "exam_format": self.exam_format,
            "exam_duration": self.exam_duration,
            "exam_info": self.read_exam_info(),
            "workspace_id": self.workspace_id,
            "extra_instructions": self.extra_instructions,
        }

    def trim_history(self, max_turns: int = 20) -> None:
        """Keep the chat history from growing without bound."""
        max_msgs = max_turns * 2          # each turn = 1 human + 1 AI message
        if len(self.chat_history) > max_msgs:
            self.chat_history = self.chat_history[-max_msgs:]
