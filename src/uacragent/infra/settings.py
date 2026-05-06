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

    llm_model: str = Field(
        default="gemini-2.5-flash",
        validation_alias=AliasChoices("LLM_MODEL", "llm_model"),
    )
    google_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("GOOGLE_API_KEY", "google_api_key"),
        repr=False,  # never appear in repr()/str() to prevent accidental logging
    )

    embedding_model: str = Field(
        default="gemini-embedding-001",
        validation_alias=AliasChoices("EMBEDDING_MODEL", "embedding_model"),
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

    workspace_root: Path = Field(
        default=Path("data"),
        validation_alias=AliasChoices("WORKSPACE_ROOT", "workspace_root"),
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
