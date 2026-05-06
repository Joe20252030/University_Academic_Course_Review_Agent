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


def get_settings() -> Settings:
    return Settings()
