from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import anyio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from financial_analytics_api.errors import install_error_handlers
from financial_analytics_api.health import router as health_router
from financial_analytics_api.logging import configure_logging
from financial_analytics_api.middleware import RequestContextMiddleware
from financial_analytics_infra.database import Database
from financial_analytics_infra.settings import Settings

ReadinessCheck = Callable[[], Awaitable[bool]]


def create_app(
    settings: Settings | None = None,
    readiness_check: ReadinessCheck | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()
    configure_logging(resolved_settings.log_level)
    database: Database | None = None

    if readiness_check is None:
        database = Database(resolved_settings.database_url)

        async def database_readiness_check() -> bool:
            assert database is not None
            return await anyio.to_thread.run_sync(database.ping)

        readiness_check = database_readiness_check

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if database is not None:
            database.close()

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.readiness_check = readiness_check
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "X-Correlation-ID", "X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    app.include_router(health_router)
    return app


app = create_app()
