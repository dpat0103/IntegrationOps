from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.routes import router as api_router
from app.api.simulator import router as simulator_router
from app.core.config import Settings, get_settings
from app.core.db import build_engine_and_session, init_db
from app.services.scheduler import LocalScheduler


DASHBOARD = Path(__file__).parent / "static" / "dashboard.html"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine, session_factory = build_engine_and_session(settings.database_url)
    if settings.auto_create_schema:
        init_db(engine)
    scheduler_holder = {"scheduler": None}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.scheduler_enabled and settings.task_mode == "local":
            scheduler = LocalScheduler(session_factory, settings)
            scheduler.start()
            scheduler_holder["scheduler"] = scheduler
        yield
        if scheduler_holder["scheduler"]:
            await scheduler_holder["scheduler"].stop()
        engine.dispose()

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.simulator_mode = "healthy"
    app.state.simulator_delay_seconds = 4.0

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)
    app.include_router(simulator_router)

    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(DASHBOARD)

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
