"""FastAPI entry point: wires settings, providers, services, API and the web frontend."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from .api.routes import router
from .config import FRONTEND_DIR, Settings, load_settings
from .providers.base import IST, MarketDataProvider, ProviderError
from .providers.factory import build_provider, build_reference
from .services.ai import AIService
from .services.analysis import AnalysisService

DEFAULT_CORS = ("http://localhost", "http://127.0.0.1", "capacitor://localhost", "https://localhost",
                "http://localhost:8000", "http://127.0.0.1:8000")


class RedactSecrets(logging.Filter):
    def __init__(self, secrets: list[str]):
        super().__init__()
        self.secrets = [s for s in secrets if s and len(s) >= 3]

    def filter(self, record: logging.LogRecord) -> bool:
        if self.secrets:
            msg = record.getMessage()
            for s in self.secrets:
                msg = msg.replace(s, "***")
            record.msg, record.args = msg, ()
        return True


def _error(status: int, code: str, message: str, details=None) -> JSONResponse:
    body = {"error": {"code": code, "message": message}, "timestamp": datetime.now(IST).isoformat()}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(status_code=status, content=body)


def create_app(settings: Settings | None = None, provider: MarketDataProvider | None = None,
               reference=None, ai_client=None) -> FastAPI:
    settings = settings or load_settings()
    import os
    redact = RedactSecrets([settings.samco_password, settings.samco_user_id, settings.samco_yob,
                            os.environ.get("ANTHROPIC_API_KEY", "")])
    for name in ("swing", "uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).addFilter(redact)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await app.state.provider.close()

    app = FastAPI(title="Swing Watchlist AI", version="1.0.0", lifespan=lifespan,
                  description="Decision-support API: stock selection and BUY/SELL/HOLD signals. No order execution.")
    app.state.settings = settings
    app.state.provider = provider or build_provider(settings)
    app.state.ai = AIService(settings, client=ai_client)
    app.state.analysis = AnalysisService(settings, app.state.provider, reference or build_reference(settings), app.state.ai)

    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins or DEFAULT_CORS),
                       allow_methods=["GET", "PUT", "OPTIONS"], allow_headers=["Content-Type"])

    @app.exception_handler(ProviderError)
    async def _provider_error(_: Request, exc: ProviderError):
        return _error(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e.get("loc", [])), "message": e.get("msg")} for e in exc.errors()]
        return _error(422, "validation_error", "Request validation failed.", details)

    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException):
        if isinstance(exc.detail, dict):
            return _error(exc.status_code, exc.detail.get("code", "error"), exc.detail.get("message", ""))
        return _error(exc.status_code, "error" if exc.status_code != 404 else "not_found", str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        logging.getLogger("swing").exception("Unhandled error: %s", type(exc).__name__)
        return _error(500, "internal_error", "Internal server error.")

    app.include_router(router)
    if FRONTEND_DIR.exists():
        app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    return app

