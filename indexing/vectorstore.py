from langchain_community.vectorstores import Chroma
from langchain_core.vectorstores import VectorStore
from langchain_openai import OpenAIEmbeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_core.documents import Document
from config import Settings
import os

def get_or_create_vectorstore(chunks: list[Document], settings: Settings) -> VectorStore:
    embeddings = GoogleGenerativeAIEmbeddings(model=settings.EMBEDDING_MODEL)
    os.makedirs(settings.CHROMA_DIR, exist_ok=True)

    return Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=settings.CHROMA_DIR
    )
