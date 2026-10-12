import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST
from app.api.routes import router
from app.api.simulator import router as simulator_router
from app.core.config import get_settings
from app.core.db import build_engine_and_session, init_db
from app.services.metrics import render_metrics
from app.services.scheduler import LocalScheduler

STATIC = Path(__file__).parent / "static"


def create_app(settings=None):
    settings = settings or get_settings()
    engine, factory = build_engine_and_session(settings.database_url)
    if settings.auto_migrate:
        init_db(engine)

    @asynccontextmanager
    async def lifespan(app):
        scheduler = (
            LocalScheduler(factory, settings)
            if settings.scheduler_enabled and settings.task_mode == "local"
            else None
        )
        if scheduler:
            scheduler.start()
        yield
        if scheduler:
            await scheduler.stop()
        engine.dispose()

    app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.session_factory = factory
    app.state.simulator_mode = "healthy"
    app.state.simulator_delay_seconds = 0.8
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Authorization"],
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.demo_session_secret or secrets.token_urlsafe(32),
        session_cookie="integrationops_session",
        max_age=settings.demo_ttl_hours * 3600,
        same_site="strict",
        https_only=settings.cookie_secure,
    )
    app.include_router(router)
    if settings.environment == "development":
        app.include_router(simulator_router)
    app.mount("/assets", StaticFiles(directory=STATIC), name="assets")

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            (
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
            )
            if request.url.path not in ("/docs", "/redoc")
            else (
                "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' https://fastapi.tiangolo.com data:; "
                "frame-ancestors 'none'; base-uri 'none'"
            )
        )
        return response

    @app.get("/", include_in_schema=False)
    def dashboard(request: Request):
        from app.api.deps import demo_owner

        demo_owner(request)
        return FileResponse(STATIC / "dashboard.html")

    @app.get("/about", include_in_schema=False)
    def about():
        return FileResponse(STATIC / "about.html")

    @app.get("/services/{integration_id}", include_in_schema=False)
    def service_detail(integration_id: int):
        return FileResponse(STATIC / "service.html")

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(render_metrics(factory), media_type=CONTENT_TYPE_LATEST)

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return FileResponse(STATIC / "favicon.svg", media_type="image/svg+xml")

    return app


app = create_app()
