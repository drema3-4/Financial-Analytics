from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from financial_analytics_api.main import create_app
from financial_analytics_infra.settings import AppEnvironment, Settings


def test_liveness_does_not_depend_on_database() -> None:
    async def database_is_down() -> bool:
        return False

    app = create_app(make_test_settings(), database_is_down)

    with TestClient(app) as client:
        live_response = client.get("/health/live")
        ready_response = client.get("/health/ready")

    assert live_response.status_code == 200
    assert live_response.json() == {"status": "alive"}
    assert ready_response.status_code == 503
    assert ready_response.headers["content-type"] == "application/problem+json"
    assert ready_response.json()["code"] == "dependency_unavailable"


def test_readiness_reports_the_database_check() -> None:
    async def database_is_up() -> bool:
        return True

    with TestClient(create_app(make_test_settings(), database_is_up)) as client:
        response = client.get("/health/ready", headers={"X-Correlation-ID": "deployment-42"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": "up", "jobs": "up", "provider": "disabled"},
    }
    assert response.headers["X-Correlation-ID"] == "deployment-42"
    assert response.headers["X-Request-ID"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "no-store"


def test_request_id_is_preserved_when_safe_and_replaced_when_unsafe() -> None:
    async def database_is_up() -> bool:
        return True

    with TestClient(create_app(make_test_settings(), database_is_up)) as client:
        preserved = client.get("/health/live", headers={"X-Request-ID": "request_123"})
        replaced = client.get("/health/live", headers={"X-Request-ID": "unsafe\nvalue"})

    assert preserved.headers["X-Request-ID"] == "request_123"
    assert replaced.headers["X-Request-ID"] != "unsafe\nvalue"


def test_not_found_uses_the_shared_problem_contract() -> None:
    async def database_is_up() -> bool:
        return True

    with TestClient(create_app(make_test_settings(), database_is_up)) as client:
        response = client.get("/does-not-exist")

    body = response.json()
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert body["code"] == "not_found"
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert body["correlation_id"] == response.headers["X-Correlation-ID"]


def test_unhandled_error_is_redacted() -> None:
    async def database_is_up() -> bool:
        return True

    app = create_app(make_test_settings(), database_is_up)

    @app.get("/test-error")
    async def test_error() -> None:
        raise RuntimeError("sensitive internal detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/test-error")

    assert response.status_code == 500
    assert response.json()["detail"] == "The server could not complete the request."
    assert "sensitive" not in response.text


def test_application_starts_without_calling_readiness() -> None:
    calls = 0

    async def readiness_probe() -> bool:
        nonlocal calls
        calls += 1
        return False

    app = create_app(make_test_settings(), readiness_probe)

    with TestClient(app) as client:
        assert calls == 0
        assert client.get("/health/live").status_code == 200
        assert calls == 0


def test_non_http_scope_passes_through_request_middleware() -> None:
    observed = False

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        nonlocal observed
        observed = True
        yield

    app = FastAPI(lifespan=lifespan)
    from financial_analytics_api.middleware import RequestContextMiddleware

    app.add_middleware(RequestContextMiddleware)
    with TestClient(app):
        assert observed


def test_validation_errors_use_the_shared_problem_contract() -> None:
    async def database_is_up() -> bool:
        return True

    app = create_app(make_test_settings(), database_is_up)

    @app.get("/test-validation/{value}")
    async def validation_target(value: int) -> dict[str, int]:
        return {"value": value}

    with TestClient(app) as client:
        response = client.get("/test-validation/not-an-integer")

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert response.json()["errors"][0]["location"] == ["path", "value"]


def make_test_settings() -> Settings:
    return Settings(app_env=AppEnvironment.TEST, _env_file=None)
