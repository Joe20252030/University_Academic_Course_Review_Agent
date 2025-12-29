from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_core.documents import Document
from pathlib import Path

def load_documents(paths: list[str]) -> list[Document]:
    docs = []
    for path in paths:
        ext = Path(path).suffix.lower()
        if ext == ".pdf":
            docs.extend(PyPDFLoader(path).load())
        elif ext in [".txt", ".md"]:
            docs.extend(TextLoader(path).load())
        else:
            raise ValueError(f"Unsupported file type: {path}")
    return docs
