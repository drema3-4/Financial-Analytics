from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from httpx2 import Response

from financial_analytics_api.main import create_app
from financial_analytics_app.identity import AuthService
from financial_analytics_infra.security import HmacSecretProvider, InMemorySlidingWindowRateLimiter
from financial_analytics_infra.settings import AppEnvironment, Settings
from tests.fakes_identity import FakeIdentityStore, FakePasswordHashes, MutableClock


def make_client() -> TestClient:
    settings = Settings(
        app_env=AppEnvironment.TEST,
        session_cookie_secure=True,
        cors_origins=["https://app.example.test"],
        _env_file=None,
    )
    service = AuthService(
        FakeIdentityStore(),
        FakePasswordHashes(),
        HmacSecretProvider("s" * 32),
        HmacSecretProvider("c" * 32),
        InMemorySlidingWindowRateLimiter(),
        clock=MutableClock(datetime.now(UTC)),
    )

    async def ready() -> bool:
        return True

    return TestClient(
        create_app(settings, ready, service),
        base_url="https://testserver",
    )


def bootstrap(client: TestClient) -> Response:
    return client.post(
        "/api/v1/auth/bootstrap",
        json={
            "email": "master@example.com",
            "password": "correct horse battery staple",
            "base_currency": "RUB",
            "locale": "ru-RU",
            "timezone": "Europe/Saratov",
        },
    )


def test_cookie_auth_profile_csrf_refresh_logout_and_problem_contract() -> None:
    with make_client() as client:
        anonymous = client.get("/api/v1/profile")
        assert anonymous.status_code == 401
        assert anonymous.headers["content-type"].startswith("application/problem+json")

        created = bootstrap(client)
        assert created.status_code == 201
        assert created.json()["email"] == "master@example.com"
        set_cookie = created.headers.get_list("set-cookie")
        assert any("fa_access=" in value and "HttpOnly" in value for value in set_cookie)
        assert any("fa_refresh=" in value and "HttpOnly" in value for value in set_cookie)
        assert all("Secure" in value and "SameSite=strict" in value for value in set_cookie)
        assert all("correct horse" not in value for value in set_cookie)

        profile = client.get("/api/v1/profile")
        assert profile.status_code == 200
        csrf = client.cookies.get("fa_csrf")
        assert csrf is not None

        rejected = client.post("/api/v1/auth/logout")
        assert rejected.status_code == 403
        assert rejected.json()["code"] == "csrf_validation_failed"

        refreshed = client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf})
        assert refreshed.status_code == 200
        rotated_csrf = client.cookies.get("fa_csrf")
        assert rotated_csrf != csrf
        assert rotated_csrf is not None

        logged_out = client.post("/api/v1/auth/logout-all", headers={"X-CSRF-Token": rotated_csrf})
        assert logged_out.status_code == 204
        assert client.get("/api/v1/profile").status_code == 401


def test_bootstrap_replay_login_rate_limit_and_strict_cors() -> None:
    with make_client() as client:
        assert bootstrap(client).status_code == 201
        assert bootstrap(client).status_code == 409

        client.cookies.clear()
        login = client.post(
            "/api/v1/auth/login",
            json={
                "email": "master@example.com",
                "password": "correct horse battery staple",
            },
        )
        assert login.status_code == 200

        for _ in range(AuthService.LOGIN_LIMIT - 1):
            response = client.post(
                "/api/v1/auth/login",
                json={"email": "master@example.com", "password": "wrong"},
            )
            assert response.status_code == 401
        limited = client.post(
            "/api/v1/auth/login",
            json={"email": "master@example.com", "password": "wrong"},
        )
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == "60"

        allowed = client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": "https://app.example.test",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-CSRF-Token",
            },
        )
        assert allowed.status_code == 200
        assert allowed.headers["access-control-allow-origin"] == "https://app.example.test"

        denied = client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert denied.status_code == 400
        assert "access-control-allow-origin" not in denied.headers


def test_identity_input_validation_never_echoes_password() -> None:
    with make_client() as client:
        password = "too-short"
        invalid = client.post(
            "/api/v1/auth/bootstrap",
            json={
                "email": "not-an-email",
                "password": password,
                "base_currency": "rub",
                "locale": "invalid_locale",
                "timezone": "Mars/Olympus",
            },
        )
        assert invalid.status_code == 422
        assert invalid.json()["code"] == "validation_error"
        assert password not in invalid.text
