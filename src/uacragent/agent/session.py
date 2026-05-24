"""AgentSession — all mutable state for one conversation session."""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from langchain_core.messages import BaseMessage
from langchain_core.retrievers import BaseRetriever

logger = logging.getLogger(__name__)

from uacragent.domain.types import DocumentType


# ---------------------------------------------------------------------------
# Thread-safe chat-history store
# ---------------------------------------------------------------------------

class _HistoryStore:
    """Thread-safe wrapper around a list of LangChain messages.

    Plain list mutations (two sequential ``.append()`` calls for one turn,
    then ``history = history[:-2]`` for cancel) are individually atomic in
    CPython but the *sequence* is not — a cancel arriving between the two
    appends would leave a dangling human message with no AI reply.

    ``_HistoryStore`` exposes atomic operations for the two multi-step cases:

    * ``append_turn(human, ai)``   — inserts both messages under one lock.
    * ``pop_last_turn()``          — removes the last pair under one lock.

    All other access (``len``, ``__iter__``, ``__getitem__``) is also guarded.
    ``snapshot()`` returns a shallow copy that is safe to iterate outside the
    lock (the typical use-case: building the message list for an LLM call).
    """

    __slots__ = ("_lock", "_messages")

    def __init__(self, messages: list[BaseMessage] | None = None) -> None:
        self._lock: threading.Lock = threading.Lock()
        self._messages: list[BaseMessage] = list(messages) if messages else []

    # ── Atomic multi-step operations ──────────────────────────────────────

    def append_turn(self, human: BaseMessage, ai: BaseMessage) -> None:
        """Atomically append one human message followed by one AI message."""
        with self._lock:
            self._messages.append(human)
            self._messages.append(ai)

    def pop_last_turn(self) -> bool:
        """Atomically remove the last (human, AI) pair.

        Returns ``True`` when a pair was removed, ``False`` when fewer than
        two messages were present (no-op).
        """
        with self._lock:
            if len(self._messages) >= 2:
                del self._messages[-2:]
                return True
            return False

    def trim(self, max_turns: int = 20) -> None:
        """Truncate the history to at most *max_turns* turns under the lock."""
        max_msgs = max_turns * 2  # one turn = 1 human + 1 AI message
        with self._lock:
            if len(self._messages) > max_msgs:
                self._messages = self._messages[-max_msgs:]

    # ── Safe read operations ──────────────────────────────────────────────

    def snapshot(self) -> list[BaseMessage]:
        """Return a shallow copy that is safe to iterate without holding the lock."""
        with self._lock:
            return list(self._messages)

    def clear(self) -> None:
        """Remove all messages."""
        with self._lock:
            self._messages.clear()

    # ── Protocol / dunder helpers ─────────────────────────────────────────

    def __len__(self) -> int:
        with self._lock:
            return len(self._messages)

    def __bool__(self) -> bool:
        with self._lock:
            return bool(self._messages)

    def __iter__(self):
        """Iterate over a point-in-time snapshot — safe outside the lock."""
        return iter(self.snapshot())

    def __getitem__(self, key):
        with self._lock:
            return self._messages[key]

    def __repr__(self) -> str:  # pragma: no cover
        with self._lock:
            return f"_HistoryStore({self._messages!r})"


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
    # Accepts a list[BaseMessage] for backward-compatibility (e.g. dict_to_session
    # passes the plain list returned by _deserialise_history).  __post_init__
    # wraps it in _HistoryStore so all callers always see the thread-safe API.
    chat_history: _HistoryStore = field(default_factory=_HistoryStore)

    # Cache for read_exam_info() — invalidated when exam_info_path changes.
    _exam_info_cache: tuple[str, str] | None = field(default=None, repr=False)

    # ── Initialisation ────────────────────────────────────────────────────

    def __post_init__(self) -> None:
        # Wrap a plain list passed at construction time (e.g. from dict_to_session).
        if isinstance(self.chat_history, list):
            self.chat_history = _HistoryStore(self.chat_history)

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
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read exam info sheet %r: %s", path, exc)
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
        self.chat_history.trim(max_turns)
