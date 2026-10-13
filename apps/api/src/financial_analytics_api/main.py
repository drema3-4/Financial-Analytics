from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import anyio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from financial_analytics_api.errors import install_error_handlers
from financial_analytics_api.health import router as health_router
from financial_analytics_api.identity import router as identity_router
from financial_analytics_api.ledger import router as ledger_router
from financial_analytics_api.logging import configure_logging
from financial_analytics_api.middleware import RequestContextMiddleware
from financial_analytics_api.scheduling import router as scheduling_router
from financial_analytics_app.identity import AuthService
from financial_analytics_app.ledger import LedgerService
from financial_analytics_app.scheduling import SchedulingService
from financial_analytics_infra.database import Database
from financial_analytics_infra.identity import PostgresIdentityStore
from financial_analytics_infra.repositories import PostgresUnitOfWorkFactory
from financial_analytics_infra.scheduling import PostgresSchedulingRepository
from financial_analytics_infra.security import (
    Argon2idPasswordHashes,
    HmacSecretProvider,
    InMemorySlidingWindowRateLimiter,
)
from financial_analytics_infra.settings import Settings

ReadinessCheck = Callable[[], Awaitable[bool]]


def create_app(
    settings: Settings | None = None,
    readiness_check: ReadinessCheck | None = None,
    auth_service: AuthService | None = None,
    ledger_service: LedgerService | None = None,
    scheduling_service: SchedulingService | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()
    configure_logging(resolved_settings.log_level)
    database: Database | None = None
    identity_store: PostgresIdentityStore | None = None

    if auth_service is None:
        identity_store = PostgresIdentityStore(resolved_settings.database_url)
        auth_service = AuthService(
            identity_store,
            Argon2idPasswordHashes(),
            HmacSecretProvider(resolved_settings.session_secret),
            HmacSecretProvider(resolved_settings.csrf_secret),
            InMemorySlidingWindowRateLimiter(),
        )

    if ledger_service is None or scheduling_service is None or readiness_check is None:
        database = Database(resolved_settings.database_url)

    if ledger_service is None:
        assert database is not None
        ledger_service = LedgerService(PostgresUnitOfWorkFactory(database.engine))

    if scheduling_service is None:
        assert database is not None
        scheduling_service = SchedulingService(PostgresSchedulingRepository(database.engine))

    if readiness_check is None:

        async def database_readiness_check() -> bool:
            assert database is not None
            return await anyio.to_thread.run_sync(database.ping)

        readiness_check = database_readiness_check

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if database is not None:
            database.close()
        if identity_store is not None:
            identity_store.close()

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.readiness_check = readiness_check
    app.state.auth_service = auth_service
    app.state.ledger_service = ledger_service
    app.state.scheduling_service = scheduling_service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Accept",
            "Content-Type",
            "X-Correlation-ID",
            "X-CSRF-Token",
            "Idempotency-Key",
            "X-Request-ID",
        ],
        expose_headers=["Retry-After", "X-Correlation-ID", "X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(identity_router)
    app.include_router(ledger_router)
    app.include_router(scheduling_router)
    return app


app = create_app()
