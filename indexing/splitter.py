from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from config import Settings

def split_documents(docs: list[Document], settings: Settings) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP
    )
    return splitter.split_documents(docs)
