from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    LLM_MODEL: str = "gemini-2.5-pro"
    EMBEDDING_MODEL: str = "gemini-embedding-001"

    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 150
    RETRIEVER_K: int = 8

    DATA_DIR: str = "data"
    CHROMA_DIR: str = "data/chroma_db"
    OUTPUT_DIR: str = "data/outputs"

def get_settings() -> Settings:
    return Settings()
