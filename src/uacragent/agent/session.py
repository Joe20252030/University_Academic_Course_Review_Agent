"""AgentSession — all mutable state for one conversation session."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

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
    workspace_id: str = "default"
    workspace_folder: Optional[Path] = field(default=None)  # user-chosen folder; overrides workspace_id
    extra_instructions: str = ""

    # ── Files ─────────────────────────────────────────────────────────────
    classified_files: dict[DocumentType, list[str]] = field(default_factory=dict)

    # ── Runtime (not serialised) ───────────────────────────────────────────
    retriever: BaseRetriever | None = field(default=None, repr=False)
    chat_history: list[BaseMessage] = field(default_factory=list)

    # ── Helpers ───────────────────────────────────────────────────────────

    def has_files(self) -> bool:
        return any(paths for paths in self.classified_files.values())

    def active_files(self) -> dict[DocumentType, list[str]]:
        """Return only doc-type buckets that have at least one file."""
        return {k: v for k, v in self.classified_files.items() if v}

    def read_exam_info(self) -> str:
        """Read and return the content of the exam info sheet file, or ''."""
        path = self.exam_info_path
        if not path:
            return ""
        try:
            p = Path(path)
            suffix = p.suffix.lower()
            if suffix == ".pdf":
                from langchain_community.document_loaders import PyPDFLoader
                docs = PyPDFLoader(path).load()
                return "\n".join(d.page_content for d in docs).strip()
            if suffix == ".docx":
                import docx2txt
                return docx2txt.process(path).strip()
            return p.read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            return ""

    def to_user_prefs(self) -> dict:
        """Build the user_prefs dict expected by AgentService / pipeline."""
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
