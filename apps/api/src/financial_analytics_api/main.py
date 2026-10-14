from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import anyio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from financial_analytics_api.advice import router as advice_router
from financial_analytics_api.analytics import router as analytics_router
from financial_analytics_api.deposits import router as deposits_router
from financial_analytics_api.errors import install_error_handlers
from financial_analytics_api.forecast import router as forecast_router
from financial_analytics_api.health import router as health_router
from financial_analytics_api.identity import router as identity_router
from financial_analytics_api.ledger import router as ledger_router
from financial_analytics_api.logging import configure_logging
from financial_analytics_api.middleware import RequestContextMiddleware
from financial_analytics_api.scheduling import router as scheduling_router
from financial_analytics_app.advice import AdviceService, DisabledAdviceProvider
from financial_analytics_app.analytics import AnalyticsService
from financial_analytics_app.deposits import DepositService
from financial_analytics_app.forecast import ForecastService
from financial_analytics_app.identity import AuthService
from financial_analytics_app.ledger import LedgerService
from financial_analytics_app.ports import AdviceProvider, AdviceProviderCapabilities
from financial_analytics_app.scheduling import SchedulingService
from financial_analytics_infra.advice import OpenAICompatibleAdviceProvider
from financial_analytics_infra.database import Database
from financial_analytics_infra.identity import PostgresIdentityStore
from financial_analytics_infra.repositories import PostgresUnitOfWorkFactory
from financial_analytics_infra.scheduling import PostgresSchedulingRepository
from financial_analytics_infra.security import (
    Argon2idPasswordHashes,
    HmacSecretProvider,
    InMemorySlidingWindowRateLimiter,
)
from financial_analytics_infra.settings import LlmProvider, Settings

ReadinessCheck = Callable[[], Awaitable[bool]]


def create_app(
    settings: Settings | None = None,
    readiness_check: ReadinessCheck | None = None,
    auth_service: AuthService | None = None,
    ledger_service: LedgerService | None = None,
    scheduling_service: SchedulingService | None = None,
    deposit_service: DepositService | None = None,
    analytics_service: AnalyticsService | None = None,
    forecast_service: ForecastService | None = None,
    advice_service: AdviceService | None = None,
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

    if (
        ledger_service is None
        or scheduling_service is None
        or deposit_service is None
        or analytics_service is None
        or forecast_service is None
        or readiness_check is None
    ):
        database = Database(resolved_settings.database_url)

    if ledger_service is None:
        assert database is not None
        ledger_service = LedgerService(PostgresUnitOfWorkFactory(database.engine))

    if scheduling_service is None:
        assert database is not None
        scheduling_service = SchedulingService(PostgresSchedulingRepository(database.engine))

    if deposit_service is None:
        assert database is not None
        deposit_service = DepositService(PostgresUnitOfWorkFactory(database.engine))

    if analytics_service is None:
        assert database is not None
        analytics_service = AnalyticsService(PostgresUnitOfWorkFactory(database.engine))

    if forecast_service is None:
        assert database is not None
        forecast_service = ForecastService(PostgresUnitOfWorkFactory(database.engine))

    if advice_service is None:
        advice_provider: AdviceProvider
        if resolved_settings.llm_provider is LlmProvider.DISABLED:
            advice_provider = DisabledAdviceProvider()
        else:
            assert resolved_settings.llm_base_url is not None
            advice_provider = OpenAICompatibleAdviceProvider(
                base_url=resolved_settings.llm_base_url,
                api_key=resolved_settings.llm_api_key,
                model=resolved_settings.llm_model,
                timeout_seconds=resolved_settings.llm_timeout_seconds,
                max_retries=resolved_settings.llm_max_retries,
                retry_backoff_seconds=resolved_settings.llm_retry_backoff_seconds,
                endpoint_scope=resolved_settings.llm_endpoint_scope.value,
                capabilities=AdviceProviderCapabilities(
                    json_schema=resolved_settings.llm_supports_json_schema,
                    system_messages=resolved_settings.llm_supports_system_messages,
                    non_thinking=resolved_settings.llm_supports_non_thinking,
                ),
            )
        advice_service = AdviceService(
            analytics_service,
            forecast_service,
            advice_provider,
            max_tokens=resolved_settings.llm_max_tokens,
        )

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
    app.state.deposit_service = deposit_service
    app.state.analytics_service = analytics_service
    app.state.forecast_service = forecast_service
    app.state.advice_service = advice_service
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
    app.include_router(deposits_router)
    app.include_router(analytics_router)
    app.include_router(forecast_router)
    app.include_router(advice_router)
    return app


app = create_app()
