from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from collections.abc import Callable

from langchain_community.document_loaders import PyPDFLoader, TextLoader, Docx2txtLoader
from langchain_core.documents import Document
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from uacragent.domain.errors import IngestError
from uacragent.domain.types import DocumentType
from uacragent.infra.settings import Settings
from uacragent.infra.workspace import WorkspacePaths

logger = logging.getLogger(__name__)

# Maximum iterations for filename collision resolution.  At 1 000 a collision
# that cannot be resolved is practically impossible with human-uploaded files;
# anything beyond suggests a filesystem problem rather than a collision.
_MAX_COLLISION_COUNTER = 1_000


# ---------------------------------------------------------------------------
# Multi-stage splitting pipeline definitions
# ---------------------------------------------------------------------------
# Each document type has a pipeline: an ordered list of splitting stages.
# A stage is a callable  list[Document] -> list[Document].
#
# Strategy rationale:
#   Textbook   – header split to isolate chapters/sections, then recursive
#                character split to break long sections into retrievable chunks.
#   Syllabus   – header split to isolate policy/schedule sections, then small
#                character split so each policy item is its own chunk.
#   Lecture    – sentence-aware recursive split (uses sentence separators first)
#                to keep slide-level ideas intact.
#   Past Exam  – regex split on question boundaries (numbered items) to keep
#                each question together, then small character split for long Qs.
#   Assignment – same boundary approach as past exams but tuned for problem
#                sets (Problem / Question / Exercise headers).
#   Other      – standard recursive character split as a safe default.
# ---------------------------------------------------------------------------


def _make_header_then_recursive(
    headers_to_split_on: list[tuple[str, str]],
    chunk_size: int,
    chunk_overlap: int,
) -> list[Callable[[list[Document]], list[Document]]]:
    """Return a 2-stage pipeline: markdown-header split, then recursive."""

    def _header_stage(docs: list[Document]) -> list[Document]:
        md_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=headers_to_split_on,
            strip_headers=False,
        )
        out: list[Document] = []
        for doc in docs:
            splits = md_splitter.split_text(doc.page_content)
            for split in splits:
                # Merge parent metadata into each split
                merged_meta = {**doc.metadata, **split.metadata}
                out.append(Document(page_content=split.page_content, metadata=merged_meta))
        return out

    def _recursive_stage(docs: list[Document]) -> list[Document]:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        return splitter.split_documents(docs)

    return [_header_stage, _recursive_stage]


def _make_sentence_aware_recursive(
    chunk_size: int,
    chunk_overlap: int,
) -> list[Callable[[list[Document]], list[Document]]]:
    """Single-stage pipeline with sentence-aware separators for lecture notes."""

    def _split(docs: list[Document]) -> list[Document]:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=[
                "\n\n",        # paragraph break
                "\n",          # line break
                ". ",          # sentence end
                "? ",          # question end
                "! ",          # exclamation end
                "; ",          # semicolon (list items, definitions)
                ", ",          # comma
                " ",           # word boundary
                "",            # character fallback
            ],
        )
        return splitter.split_documents(docs)

    return [_split]


def _make_question_boundary_split(
    boundary_pattern: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[Callable[[list[Document]], list[Document]]]:
    """2-stage pipeline: regex split on question/problem boundaries, then
    recursive character split for any chunks that are still too large."""

    compiled = re.compile(boundary_pattern)

    def _boundary_stage(docs: list[Document]) -> list[Document]:
        out: list[Document] = []
        for doc in docs:
            parts = compiled.split(doc.page_content)
            for part in parts:
                part = part.strip()
                if part:
                    out.append(Document(page_content=part, metadata=dict(doc.metadata)))
        return out

    def _recursive_stage(docs: list[Document]) -> list[Document]:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        return splitter.split_documents(docs)

    return [_boundary_stage, _recursive_stage]


def _make_recursive_only(
    chunk_size: int,
    chunk_overlap: int,
) -> list[Callable[[list[Document]], list[Document]]]:
    """Single-stage standard recursive split."""

    def _split(docs: list[Document]) -> list[Document]:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        return splitter.split_documents(docs)

    return [_split]


# ---------------------------------------------------------------------------
# Pipeline registry – one pipeline per document type
# ---------------------------------------------------------------------------

def _get_pipeline(doc_type: DocumentType) -> list[Callable[[list[Document]], list[Document]]]:
    """Return the multi-stage splitting pipeline for the given document type."""

    if doc_type == DocumentType.textbook:
        # Stage 1: split on markdown headers (chapter / section / subsection)
        # Stage 2: recursive split to max 1500-char retrievable chunks
        return _make_header_then_recursive(
            headers_to_split_on=[
                ("#", "chapter"),
                ("##", "section"),
                ("###", "subsection"),
            ],
            chunk_size=1500,
            chunk_overlap=200,
        )

    if doc_type == DocumentType.syllabus:
        # Stage 1: header split to isolate policy / schedule / grading sections
        # Stage 2: small recursive split so each rule/policy is a chunk
        return _make_header_then_recursive(
            headers_to_split_on=[
                ("#", "section"),
                ("##", "subsection"),
            ],
            chunk_size=800,
            chunk_overlap=100,
        )

    if doc_type == DocumentType.lecture_note:
        # Sentence-aware split keeps slide bullet points together
        return _make_sentence_aware_recursive(
            chunk_size=1000,
            chunk_overlap=150,
        )

    if doc_type == DocumentType.past_exam:
        # Stage 1: split on question boundaries  (1. / Q1 / Question 1 / (a) etc.)
        # Stage 2: recursive split for any oversized questions
        return _make_question_boundary_split(
            boundary_pattern=(
                r"(?=\n\s*(?:"
                r"\d+[\.\)]\s"          # "1. " or "1) "
                r"|[Qq](?:uestion)?\s*\d+"  # "Q1", "Question 1"
                r"|Part\s+[A-Za-z0-9]"  # "Part A", "Part 1"
                r"|\([a-z]\)"           # "(a)"
                r"))"
            ),
            chunk_size=500,
            chunk_overlap=80,
        )

    if doc_type == DocumentType.assignment:
        # Stage 1: split on problem/exercise boundaries
        # Stage 2: recursive split for long problems
        return _make_question_boundary_split(
            boundary_pattern=(
                r"(?=\n\s*(?:"
                r"(?:Problem|Exercise|Task|Question)\s*\d+"  # "Problem 1"
                r"|\d+[\.\)]\s"        # "1. " or "1) "
                r"|\([a-z]\)"          # "(a)"
                r"))"
            ),
            chunk_size=600,
            chunk_overlap=100,
        )

    # DocumentType.other — safe default
    return _make_recursive_only(chunk_size=1000, chunk_overlap=150)


def run_splitting_pipeline(
    docs: list[Document],
    doc_type: DocumentType,
) -> list[Document]:
    """Execute the multi-stage splitting pipeline for the given document type.

    Each stage receives the output of the previous stage.  Metadata for
    ``doc_type`` is stamped on every resulting chunk.
    """
    pipeline = _get_pipeline(doc_type)
    current = docs
    for stage in pipeline:
        current = stage(current)

    # Stamp doc_type on every chunk
    for chunk in current:
        chunk.metadata["doc_type"] = doc_type.value

    return current


# ---------------------------------------------------------------------------
# DocumentLoader
# ---------------------------------------------------------------------------

class DocumentLoader:
    """Loads and processes documents with multi-stage type-aware splitting."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def load_single_file(self, path: str) -> list[Document]:
        """Load a single file and return raw LangChain Documents.

        Supported formats:
        - PDF  (.pdf)   — via PyPDFLoader (text-layer extraction)
        - Word (.docx)  — via Docx2txtLoader
        - Text (.txt, .md, .py, .js, .ts, .html, .htm, .xml, .json)
        - CSV  (.csv)   — read and formatted as a plain-text table
        """
        try:
            ext = Path(path).suffix.lower()
            if ext == ".pdf":
                return PyPDFLoader(path).load()
            elif ext in {".txt", ".md", ".py", ".js", ".ts",
                         ".html", ".htm", ".xml", ".json"}:
                return TextLoader(path, encoding="utf-8").load()
            elif ext == ".docx":
                return Docx2txtLoader(path).load()
            elif ext == ".csv":
                return self._load_csv(path)
            else:
                raise IngestError(f"Unsupported file type: {path}")
        except IngestError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise IngestError(f"Failed to load {path}: {exc}") from exc

    @staticmethod
    def _load_csv(path: str) -> list[Document]:
        """Load a CSV file as multiple Documents — one per chunk of rows.

        Returns one Document per chunk of N data rows (default 10), each
        prepended with the header row.  This avoids returning a single giant
        Document that would be chunked arbitrarily by the text splitter and
        could cut across row boundaries, losing row context.

        Empty CSVs return a single placeholder document.
        """
        import csv as _csv

        with open(path, newline="", encoding="utf-8", errors="replace") as fh:
            reader = _csv.reader(fh)
            rows = list(reader)

        if not rows:
            return [Document(page_content="(empty CSV)", metadata={"source": path})]

        header = rows[0]
        header_line = " | ".join(header)
        data_rows = rows[1:]

        if not data_rows:
            content = f"[CSV file: {Path(path).name}]\n\n{header_line}"
            return [Document(page_content=content, metadata={"source": path})]

        chunk_size = 10
        docs: list[Document] = []
        for start in range(0, len(data_rows), chunk_size):
            batch = data_rows[start:start + chunk_size]
            body = "\n".join(" | ".join(r) for r in batch)
            content = (
                f"[CSV file: {Path(path).name} — rows {start + 1}–{start + len(batch)}]\n\n"
                f"{header_line}\n{body}"
            )
            docs.append(Document(page_content=content, metadata={"source": path}))
        return docs

    def copy_to_workspace(
        self,
        source_path: str,
        doc_type: DocumentType,
        workspace_paths: WorkspacePaths,
    ) -> str:
        """Copy a file to the appropriate classified folder in the workspace.

        If an existing workspace copy with the same content is found, that path
        is returned immediately without creating a new copy.  This prevents the
        same file from being re-indexed every time the user clicks Apply, which
        would accumulate duplicate content in the vector store.

        Returns the path of the workspace copy (new or reused).
        """
        import filecmp

        src = Path(source_path)
        if not src.exists():
            raise IngestError(f"Source file not found: {source_path}")

        dest_folder = workspace_paths.doc_folders.get(doc_type, workspace_paths.uploads)
        dest_folder.mkdir(parents=True, exist_ok=True)
        dest_path = dest_folder / src.name

        # If the primary destination already exists and has identical content,
        # reuse it — no new copy needed.  This is the common case when the user
        # clicks Apply multiple times without changing their file list.
        if dest_path.exists():
            try:
                if filecmp.cmp(str(src), str(dest_path), shallow=False):
                    return str(dest_path)
            except OSError:
                pass  # fall through to normal copy/rename logic

        # Primary destination exists but holds DIFFERENT content — find a free
        # suffixed name.  Also reuse any suffixed copy whose content matches.
        counter = 1
        candidate = dest_path
        while candidate.exists() and counter <= _MAX_COLLISION_COUNTER:
            stem = src.stem
            suffix = src.suffix
            candidate = dest_folder / f"{stem}_{counter}{suffix}"
            if candidate.exists():
                try:
                    if filecmp.cmp(str(src), str(candidate), shallow=False):
                        return str(candidate)
                except OSError:
                    pass
            counter += 1

        if counter > _MAX_COLLISION_COUNTER:
            raise IngestError(
                f"Could not find a unique filename for {src.name} in {dest_folder} "
                f"after {_MAX_COLLISION_COUNTER} attempts. "
                "The destination folder may contain an unexpected number of files."
            )

        shutil.copy2(str(src), str(candidate))
        return str(candidate)

    def split_documents(
        self,
        docs: list[Document],
        doc_type: DocumentType = DocumentType.other,
    ) -> list[Document]:
        """Split documents using a multi-stage type-specific pipeline."""
        try:
            return run_splitting_pipeline(docs, doc_type)
        except Exception as exc:  # noqa: BLE001
            raise IngestError(f"Failed to split documents: {exc}") from exc

    def load_and_split_classified(
        self,
        classified_files: dict[DocumentType, list[str]],
        workspace_paths: WorkspacePaths | None = None,
    ) -> list[Document]:
        """Load and split files by their document type classification.

        Args:
            classified_files: Mapping of DocumentType to list of file paths
            workspace_paths: If provided, copy files to classified folders

        Returns:
            Combined list of all chunks with doc_type metadata
        """
        all_chunks: list[Document] = []

        # Track resolved paths across ALL doc types so the same physical file
        # is never loaded and embedded twice even when the user adds it to
        # multiple document-type buckets.
        _globally_seen: set[str] = set()

        for doc_type, paths in classified_files.items():
            # Deduplicate within this doc type (preserve order).
            unique_paths = list(dict.fromkeys(paths))
            if len(unique_paths) < len(paths):
                logger.warning(
                    "Duplicate file paths found for %s; deduplicating (%d → %d).",
                    doc_type, len(paths), len(unique_paths),
                )

            for path in unique_paths:
                # Cross-type duplicate check: compare resolved source paths so
                # the same file under two doc types is only indexed once (under
                # whichever bucket it appears in first).
                resolved = str(Path(path).resolve())
                if resolved in _globally_seen:
                    logger.warning(
                        "File '%s' was already processed under another document "
                        "type and will not be indexed again to avoid duplicate "
                        "content in the vector store.",
                        Path(path).name,
                    )
                    continue
                _globally_seen.add(resolved)

                # Optionally copy to workspace
                if workspace_paths:
                    path = self.copy_to_workspace(path, doc_type, workspace_paths)

                # Load and split with multi-stage type-specific pipeline
                docs = self.load_single_file(path)
                chunks = self.split_documents(docs, doc_type)
                all_chunks.extend(chunks)

        return all_chunks

