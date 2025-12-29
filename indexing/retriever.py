from config import Settings
from langchain_core.vectorstores import VectorStore
from langchain_core.retrievers import BaseRetriever

def build_retriever(vectorstore: VectorStore, settings: Settings) -> BaseRetriever:
    return vectorstore.as_retriever(
        search_kwargs={"k": settings.RETRIEVER_K}
    )
