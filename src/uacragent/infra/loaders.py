from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader, TextLoader, Docx2txtLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from uacragent.domain.errors import IngestError
from uacragent.domain.types import DocumentType
from uacragent.infra.settings import Settings
from uacragent.infra.workspace import WorkspacePaths


@dataclass
class SplittingConfig:
    """Configuration for document splitting based on document type."""
    chunk_size: int
    chunk_overlap: int


# Type-specific splitting configurations
# Different document types benefit from different chunking strategies
SPLITTING_CONFIGS: dict[DocumentType, SplittingConfig] = {
    # Syllabus: structured, smaller chunks to capture discrete info
    DocumentType.syllabus: SplittingConfig(chunk_size=800, chunk_overlap=100),
    # Lecture notes: medium chunks, moderate overlap for context
    DocumentType.lecture_note: SplittingConfig(chunk_size=1000, chunk_overlap=150),
    # Textbook: larger chunks to preserve explanations and examples
    DocumentType.textbook: SplittingConfig(chunk_size=1500, chunk_overlap=200),
    # Assignments: smaller chunks to isolate individual problems/questions
    DocumentType.assignment: SplittingConfig(chunk_size=600, chunk_overlap=100),
    # Past exams: smaller chunks to isolate questions and answers
    DocumentType.past_exam: SplittingConfig(chunk_size=500, chunk_overlap=80),
    # Other: use default settings
    DocumentType.other: SplittingConfig(chunk_size=1000, chunk_overlap=150),
}


@dataclass
class ClassifiedDocument:
    """A document with its type classification and source path."""
    path: str
    doc_type: DocumentType
    documents: list[Document]


class DocumentLoader:
    """Loads and processes documents with type-aware splitting."""

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

        # Avoid overwriting - add suffix if file exists
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
        """Split documents using type-specific chunking strategy."""
        config = SPLITTING_CONFIGS.get(doc_type, SPLITTING_CONFIGS[DocumentType.other])

        try:
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=config.chunk_size,
                chunk_overlap=config.chunk_overlap,
            )
            chunks = splitter.split_documents(docs)

            # Add document type metadata to each chunk
            for chunk in chunks:
                chunk.metadata["doc_type"] = doc_type.value

            return chunks
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

                # Load and split with type-specific config
                docs = self.load_single_file(path)
                chunks = self.split_documents(docs, doc_type)
                all_chunks.extend(chunks)

        return all_chunks

    def get_splitting_config(self, doc_type: DocumentType) -> SplittingConfig:
        """Get the splitting configuration for a document type."""
        return SPLITTING_CONFIGS.get(doc_type, SPLITTING_CONFIGS[DocumentType.other])
