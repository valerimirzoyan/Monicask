from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.ami import AMIManager, build_ami
from app.api import admin_router, agent_router, tickets_router, webhook_router
from app.calls import CallStore
from app.config import Settings, get_settings
from app.db import Base, build_engine, build_session_factory
from app.services.tasks import NotFoundError, ValidationError
from app.zammad import build_zammad

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).parent / "web"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
    ami_client = build_ami(settings)
    ami_manager = AMIManager(
        client=ami_client,
        managed_queues=settings.managed_queues,
        max_attempts=settings.ami_max_attempts,
        retry_backoff=settings.ami_retry_backoff,
        timeout=settings.ami_timeout,
    )
    zammad = build_zammad(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.database_url.startswith("sqlite") and settings.environment == "dev":
            Base.metadata.create_all(engine)
        try:
            ami_manager.ensure_connected()
        except Exception as exc:
            log.warning("AMI not connected at startup: %s", exc)
        yield
        ami_client.close()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Unified agent workplace: Zammad + FreePBX/Asterisk task and availability service",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.ami = ami_client
    app.state.ami_manager = ami_manager
    app.state.zammad = zammad
    app.state.call_store = CallStore()

    app.include_router(agent_router)
    app.include_router(tickets_router)
    app.include_router(admin_router)
    app.include_router(webhook_router)

    @app.exception_handler(ValidationError)
    async def validation_handler(request: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.get("/health", tags=["system"])
    def health() -> dict:
        return {
            "status": "ok",
            "ami_mode": ami_manager.mode(),
            "ami_connected": ami_client.is_connected(),
            "zammad_mode": zammad.mode,
            "managed_queues": ami_manager.managed_queues,
        }

    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

    return app


app = create_app()
