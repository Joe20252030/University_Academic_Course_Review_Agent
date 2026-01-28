from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from uacragent.api.routes import router
from uacragent.domain.errors import UACRAgentError


def create_app() -> FastAPI:
    app = FastAPI(title="UACRAgent")
    app.include_router(router)

    @app.exception_handler(UACRAgentError)
    async def uacragent_error_handler(_, exc: UACRAgentError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return app


app = create_app()