from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_provider: str = Field(
        default="gemini",
        validation_alias=AliasChoices("LLM_PROVIDER", "llm_provider"),
    )
    llm_model: str = Field(
        default="gemini-2.5-flash",
        validation_alias=AliasChoices("LLM_MODEL", "llm_model"),
    )
    google_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("GOOGLE_API_KEY", "google_api_key"),
        repr=False,
    )
    openai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("OPENAI_API_KEY", "openai_api_key"),
        repr=False,
    )
    deepseek_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("DEEPSEEK_API_KEY", "deepseek_api_key"),
        repr=False,
    )

    # ── Embedding ─────────────────────────────────────────────────────────────
    # Which provider to use for document embeddings.
    # "gemini"  → GoogleGenerativeAIEmbeddings (needs GOOGLE_API_KEY)
    # "openai"  → OpenAIEmbeddings             (needs OPENAI_API_KEY)
    # "local"   → HuggingFace sentence-transformers (free, no key needed)
    embedding_provider: str = Field(
        default="gemini",
        validation_alias=AliasChoices("EMBEDDING_PROVIDER", "embedding_provider"),
    )
    # Gemini cloud embedding model name (used when embedding_provider == "gemini")
    embedding_model: str = Field(
        default="gemini-embedding-001",
        validation_alias=AliasChoices("EMBEDDING_MODEL", "embedding_model"),
    )
    # HuggingFace / sentence-transformers model name (used when embedding_provider == "local")
    local_embedding_model: str = Field(
        default="all-MiniLM-L6-v2",
        validation_alias=AliasChoices("LOCAL_EMBEDDING_MODEL", "local_embedding_model"),
    )

    chunk_size: int = Field(
        default=1000,
        validation_alias=AliasChoices("CHUNK_SIZE", "chunk_size"),
    )
    chunk_overlap: int = Field(
        default=150,
        validation_alias=AliasChoices("CHUNK_OVERLAP", "chunk_overlap"),
    )
    retriever_k: int = Field(
        default=8,
        validation_alias=AliasChoices("RETRIEVER_K", "retriever_k"),
    )

    # ── Rate limiting ──────────────────────────────────────────────────────────
    # Seconds to wait between consecutive LLM section calls (after each
    # completes, before the next begins). Increase if you hit 503/429 errors.
    llm_request_delay: float = Field(
        default=3.0,
        validation_alias=AliasChoices("LLM_REQUEST_DELAY", "llm_request_delay"),
    )
    # Max retry attempts on transient 503 / 429 / quota errors.
    # Keep low: retrying a rate-limited API increases total request count.
    llm_max_retries: int = Field(
        default=2,
        validation_alias=AliasChoices("LLM_MAX_RETRIES", "llm_max_retries"),
    )
    # Initial backoff delay in seconds before the first retry (doubles each
    # attempt, capped at 60 s).
    llm_retry_base_delay: float = Field(
        default=10.0,
        validation_alias=AliasChoices("LLM_RETRY_BASE_DELAY", "llm_retry_base_delay"),
    )


def get_settings() -> Settings:
    return Settings()
