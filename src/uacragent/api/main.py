from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from uacragent.api.routes import router
from uacragent.domain.errors import LLMError, UACRAgentError


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Run startup tasks before the server begins accepting requests."""
    # Load .env so API keys / provider settings are available via os.environ,
    # mirroring the desktop mode.  dotenv is a soft dependency — skip silently
    # if not installed.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    # Point HuggingFace downloads at the app-managed cache so all agent data
    # (models, sessions, index) lives in one place regardless of run mode.
    from uacragent.infra.persistence import configure_hf_cache
    configure_hf_cache()

    # Warn about env vars that look like uacragent settings but aren't recognised.
    from uacragent.infra.settings import warn_unrecognised_env_vars
    warn_unrecognised_env_vars()

    yield   # server runs here


def create_app() -> FastAPI:
    app = FastAPI(title="UACRAgent", lifespan=_lifespan)
    app.include_router(router)

    @app.exception_handler(LLMError)
    async def llm_error_handler(_, exc: LLMError) -> JSONResponse:
        """Map LLM errors to semantically correct HTTP status codes.

        Rate-limit / quota exhaustion → 429 Too Many Requests.
        Service unavailable / overload → 503 Service Unavailable.
        All other LLM errors          → 400 Bad Request.
        """
        msg = str(exc).lower()
        if any(m in msg for m in ("429", "rate limit", "quota", "resource exhausted")):
            status_code = 429
        elif any(m in msg for m in ("503", "service unavailable", "overloaded")):
            status_code = 503
        else:
            status_code = 400
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})

    @app.exception_handler(UACRAgentError)
    async def uacragent_error_handler(_, exc: UACRAgentError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return app


app = create_app()