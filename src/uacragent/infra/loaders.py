from __future__ import annotations

from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from uacragent.infra.settings import Settings
from uacragent.domain.errors import IngestError

class DocumentLoader:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        
    def load_documents(self, paths: list[str]) -> list[Document]:
        docs = []
        for path in paths:
            try:
                ext = Path(path).suffix.lower()
                if ext == ".pdf":
                    docs.extend(PyPDFLoader(path).load())
                elif ext in [".txt", ".md"]:
                    docs.extend(TextLoader(path).load())
                else:
                    raise IngestError(f"Unsupported file type: {path}")
            except IngestError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise IngestError(f"Failed to load {path}: {exc}") from exc
        return docs
    
    def split_documents(self, docs: list[Document]) -> list[Document]:
        try:
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=self.settings.chunk_size,
                chunk_overlap=self.settings.chunk_overlap,
            )
            return splitter.split_documents(docs)
        except Exception as exc:  # noqa: BLE001
            raise IngestError(f"Failed to split documents: {exc}") from exc