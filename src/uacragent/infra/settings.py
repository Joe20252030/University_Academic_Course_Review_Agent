from __future__ import annotations

import logging

from pydantic import AliasChoices, Field, field_serializer, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # Do NOT set env_file here — the app's main() calls load_dotenv() before
    # constructing Settings, which populates os.environ.  Having both would
    # cause the .env to be read twice and, worse, the env_file path resolves
    # relative to the current working directory at import time (which is "/"
    # inside a macOS .app bundle), so pydantic-settings would silently find no
    # file and the user's .env would be ignored in frozen builds.
    model_config = SettingsConfigDict(
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

    retriever_k: int = Field(
        default=8,
        validation_alias=AliasChoices("RETRIEVER_K", "retriever_k"),
    )

    # ── OpenAI server-side conversation storage ────────────────────────────────
    # OpenAI's Responses API (used by newer models such as gpt-4o and later)
    # defaults to store=True, which logs every request on the OpenAI platform
    # dashboard under "Stored outputs".  This is a privacy concern for users
    # who upload sensitive course materials.
    #
    # The app defaults to False (opt-out / privacy-first).  Set this to True
    # only if you explicitly want OpenAI to store your conversations (e.g. for
    # fine-tuning or evals purposes).
    openai_store_responses: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "OPENAI_STORE_RESPONSES", "openai_store_responses"
        ),
    )

    # ── Rate limiting ──────────────────────────────────────────────────────────
    # Named tier: "free" | "standard" | "pro" | "unlimited".
    # When set to a known tier the three concrete fields below are overridden
    # by the tier's preset values (via the model validator at the bottom).
    # Set RATE_TIER="" or leave it absent to use the raw fields directly.
    rate_tier: str = Field(
        default="free",
        validation_alias=AliasChoices("RATE_TIER", "rate_tier"),
    )
    # Seconds to wait between consecutive LLM section calls.
    # Overridden by rate_tier when a known tier is selected.
    llm_request_delay: float = Field(
        default=6.0,
        validation_alias=AliasChoices("LLM_REQUEST_DELAY", "llm_request_delay"),
    )
    # Max retry attempts on transient 503 / 429 / quota errors.
    # Overridden by rate_tier when a known tier is selected.
    llm_max_retries: int = Field(
        default=3,
        validation_alias=AliasChoices("LLM_MAX_RETRIES", "llm_max_retries"),
    )
    # Initial back-off delay in seconds before the first retry (doubles each
    # attempt, capped at 60 s).
    # Overridden by rate_tier when a known tier is selected.
    llm_retry_base_delay: float = Field(
        default=15.0,
        validation_alias=AliasChoices("LLM_RETRY_BASE_DELAY", "llm_retry_base_delay"),
    )

    # ------------------------------------------------------------------
    # Security: redact API keys from serialisation (model_dump / JSON)
    # so they are never written to logs, debug output, or config files.
    # ------------------------------------------------------------------

    @field_serializer("google_api_key", "openai_api_key", "deepseek_api_key")
    def _redact_key(self, value: str) -> str:  # noqa: PLR6301
        """Return a masked placeholder so model_dump() never exposes raw keys."""
        return "***" if value else ""

    @model_validator(mode="after")
    def _apply_rate_tier(self) -> "Settings":
        """Override the three concrete rate fields with the selected tier's values.

        This is the single place that maps ``rate_tier`` → concrete parameters,
        so adding or tweaking a tier only requires editing ``domain/rate_tiers.py``.

        The raw env-var fields (LLM_REQUEST_DELAY etc.) are ignored when a
        recognised tier is active, which keeps the system unambiguous: the tier
        is the source of truth.  Unknown / empty tier IDs fall through silently
        so hand-crafted .env overrides still work for advanced users.
        """
        from uacragent.domain.rate_tiers import RATE_TIERS
        tier = RATE_TIERS.get(self.rate_tier)
        if tier is not None:
            self.llm_request_delay   = tier.request_delay
            self.llm_max_retries     = tier.max_retries
            self.llm_retry_base_delay = tier.retry_base_delay
        return self


def get_settings() -> Settings:
    return Settings()


# ---------------------------------------------------------------------------
# Env-var typo detection
# ---------------------------------------------------------------------------

# All env var aliases recognised by Settings — exact names that pydantic-settings
# will consume.  Any env var *close* to one of these but not in the set is a
# likely typo.
_KNOWN_ALIASES: frozenset[str] = frozenset({
    "LLM_PROVIDER", "llm_provider",
    "LLM_MODEL", "llm_model",
    "GOOGLE_API_KEY", "google_api_key",
    "OPENAI_API_KEY", "openai_api_key",
    "DEEPSEEK_API_KEY", "deepseek_api_key",
    "EMBEDDING_PROVIDER", "embedding_provider",
    "EMBEDDING_MODEL", "embedding_model",
    "LOCAL_EMBEDDING_MODEL", "local_embedding_model",
    "RETRIEVER_K", "retriever_k",
    "RATE_TIER", "rate_tier",
    "LLM_REQUEST_DELAY", "llm_request_delay",
    "LLM_MAX_RETRIES", "llm_max_retries",
    "LLM_RETRY_BASE_DELAY", "llm_retry_base_delay",
    # Logging / API hardening — not pydantic-settings fields but recognised app env vars.
    "UACRAGENT_LOG_LEVEL",
    "UACRAGENT_ALLOWED_BASE_DIR",
    # OpenAI conversation storage opt-in.
    "OPENAI_STORE_RESPONSES", "openai_store_responses",
})

# Only examine env vars whose names suggest they could be uacragent settings.
_SUSPECT_PREFIXES: tuple[str, ...] = (
    "LLM_", "GOOGLE_", "OPENAI_", "DEEPSEEK_",
    "EMBEDDING_", "LOCAL_EMBEDDING_", "RETRIEVER_", "RATE_",
    "UACRAGENT_",
)


def warn_unrecognised_env_vars() -> None:
    """Log a warning for env vars that look like uacragent settings but aren't.

    Uses :func:`difflib.get_close_matches` to detect likely typos such as
    ``GOGLE_API_KEY`` (should be ``GOOGLE_API_KEY``) or ``LLM_PROIVDER``
    (should be ``LLM_PROVIDER``).  Call once at app startup so operators
    notice misconfigured ``.env`` files before a run begins.

    Two passes:
    1. Prefix filter — env vars that start with a known prefix but aren't
       in the exact aliases list (fast, catches intra-word typos like PROIVDER).
    2. Similarity scan — all remaining env vars are compared against known
       uppercase aliases with a high cutoff (catches prefix typos like GOGLE_).
    """
    import difflib
    import os

    _known_upper = {a.upper() for a in _KNOWN_ALIASES}

    # All env vars that look related but aren't in the exact known set
    unrecognised = [
        key for key in os.environ
        if key not in _KNOWN_ALIASES and key.upper() not in _known_upper
        and (
            # Known prefix but body is wrong (e.g. LLM_PROIVDER)
            any(key.upper().startswith(pfx) for pfx in _SUSPECT_PREFIXES)
            # Or contains API_KEY / _KEY suffix — catches GOGLE_API_KEY etc.
            or key.upper().endswith(("_API_KEY", "_KEY"))
        )
    ]

    for key in unrecognised:
        close = difflib.get_close_matches(
            key.upper(), list(_known_upper),
            n=1, cutoff=0.75,
        )
        if close:
            # Prefer the UPPER_CASE canonical form for readability in warnings
            match = close[0]
            logger.warning(
                "Env var '%s' is not a recognised UACRAgent setting — "
                "did you mean '%s'? This value will be ignored.",
                key, match,
            )
