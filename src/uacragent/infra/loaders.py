from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

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
# Backward-compatible dataclass (kept for get_splitting_config callers)
# ---------------------------------------------------------------------------

@dataclass
class SplittingConfig:
    """Legacy configuration — retained for any callers that inspect chunk sizes."""
    chunk_size: int
    chunk_overlap: int


SPLITTING_CONFIGS: dict[DocumentType, SplittingConfig] = {
    DocumentType.syllabus: SplittingConfig(chunk_size=800, chunk_overlap=100),
    DocumentType.lecture_note: SplittingConfig(chunk_size=1000, chunk_overlap=150),
    DocumentType.textbook: SplittingConfig(chunk_size=1500, chunk_overlap=200),
    DocumentType.assignment: SplittingConfig(chunk_size=600, chunk_overlap=100),
    DocumentType.past_exam: SplittingConfig(chunk_size=500, chunk_overlap=80),
    DocumentType.other: SplittingConfig(chunk_size=1000, chunk_overlap=150),
}


# ---------------------------------------------------------------------------
# ClassifiedDocument helper
# ---------------------------------------------------------------------------

@dataclass
class ClassifiedDocument:
    """A document with its type classification and source path."""
    path: str
    doc_type: DocumentType
    documents: list[Document]


# ---------------------------------------------------------------------------
# DocumentLoader
# ---------------------------------------------------------------------------

class DocumentLoader:
    """Loads and processes documents with multi-stage type-aware splitting."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def load_single_file(self, path: str) -> list[Document]:
        """Load a single file and return raw LangChain Documents."""
        try:
            ext = Path(path).suffix.lower()
            if ext == ".pdf":
                return PyPDFLoader(path).load()
            elif ext in [".txt", ".md"]:
                return TextLoader(path).load()
            elif ext == ".docx":
                return Docx2txtLoader(path).load()
            else:
                raise IngestError(f"Unsupported file type: {path}")
        except IngestError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise IngestError(f"Failed to load {path}: {exc}") from exc

    def load_documents(self, paths: list[str]) -> list[Document]:
        """Load multiple files and return combined raw Documents."""
        docs: list[Document] = []
        for path in paths:
            docs.extend(self.load_single_file(path))
        return docs

    def copy_to_workspace(
        self,
        source_path: str,
        doc_type: DocumentType,
        workspace_paths: WorkspacePaths,
    ) -> str:
        """Copy a file to the appropriate classified folder in the workspace.

        Returns the new path in the workspace.
        """
        src = Path(source_path)
        if not src.exists():
            raise IngestError(f"Source file not found: {source_path}")

        dest_folder = workspace_paths.doc_folders.get(doc_type, workspace_paths.uploads)
        dest_folder.mkdir(parents=True, exist_ok=True)
        dest_path = dest_folder / src.name

        # Avoid overwriting — add suffix if file exists
        counter = 1
        while dest_path.exists():
            stem = src.stem
            suffix = src.suffix
            dest_path = dest_folder / f"{stem}_{counter}{suffix}"
            counter += 1

        shutil.copy2(str(src), str(dest_path))
        return str(dest_path)

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

        for doc_type, paths in classified_files.items():
            for path in paths:
                # Optionally copy to workspace
                if workspace_paths:
                    path = self.copy_to_workspace(path, doc_type, workspace_paths)

                # Load and split with multi-stage type-specific pipeline
                docs = self.load_single_file(path)
                chunks = self.split_documents(docs, doc_type)
                all_chunks.extend(chunks)

        return all_chunks

    def get_splitting_config(self, doc_type: DocumentType) -> SplittingConfig:
        """Get the splitting configuration for a document type."""
        return SPLITTING_CONFIGS.get(doc_type, SPLITTING_CONFIGS[DocumentType.other])
