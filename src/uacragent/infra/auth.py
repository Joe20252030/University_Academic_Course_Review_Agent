from __future__ import annotations

from uacragent.domain.errors import ConfigurationError
from uacragent.infra.settings import Settings


def require_google_api_key(settings: Settings) -> None:
    """Validate required environment for Google GenAI.

    langchain-google-genai reads credentials from env at runtime, but the raw
    exception when missing is not very actionable, so we preflight it.
    """

    if not settings.google_api_key:
        raise ConfigurationError(
            "Missing GOOGLE_API_KEY. Create a .env file in the repo root with GOOGLE_API_KEY=..."
        )
