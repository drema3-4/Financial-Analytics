from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from financial_analytics_infra.settings import (
    DEFAULT_DEVELOPMENT_DATABASE_URL,
    AppEnvironment,
    Settings,
)


def test_database_url_is_masked_in_settings_representation() -> None:
    settings = Settings(
        app_env=AppEnvironment.TEST,
        database_url_secret=SecretStr("postgresql+psycopg://user:secret@database/app"),
        _env_file=None,
    )

    assert settings.database_url.endswith("@database/app")
    assert "secret" not in repr(settings)


def test_production_rejects_the_development_database_url() -> None:
    with pytest.raises(ValidationError, match="production requires an explicit DATABASE_URL"):
        Settings(
            app_env=AppEnvironment.PRODUCTION,
            database_url_secret=SecretStr(DEFAULT_DEVELOPMENT_DATABASE_URL),
            _env_file=None,
        )


def test_production_rejects_wildcard_cors() -> None:
    with pytest.raises(ValidationError, match="wildcard CORS"):
        Settings(
            app_env=AppEnvironment.PRODUCTION,
            database_url_secret=SecretStr("postgresql+psycopg://user:secret@database/app"),
            cors_origins=["*"],
            _env_file=None,
        )


def test_identity_secrets_are_masked_and_require_safe_production_values() -> None:
    settings = Settings(app_env=AppEnvironment.TEST, _env_file=None)
    assert settings.session_secret not in repr(settings)
    assert settings.csrf_secret not in repr(settings)
    assert settings.email_token_secret not in repr(settings)

    with pytest.raises(ValidationError, match="explicit identity secrets"):
        Settings(
            app_env=AppEnvironment.PRODUCTION,
            database_url_secret=SecretStr("postgresql+psycopg://user:secret@database/app"),
            _env_file=None,
        )

    with pytest.raises(ValidationError, match="at least 32"):
        Settings(
            app_env=AppEnvironment.TEST,
            session_secret_value=SecretStr("short"),
            _env_file=None,
        )
    with pytest.raises(ValidationError, match="Secure session cookies"):
        Settings(
            app_env=AppEnvironment.PRODUCTION,
            database_url_secret=SecretStr("postgresql+psycopg://user:secret@database/app"),
            session_cookie_secure=False,
            session_secret_value=SecretStr("s" * 32),
            csrf_secret_value=SecretStr("c" * 32),
            email_token_secret_value=SecretStr("e" * 32),
            _env_file=None,
        )


def test_all_environments_reject_wildcard_and_non_http_cors_origins() -> None:
    with pytest.raises(ValidationError, match="wildcard CORS"):
        Settings(app_env=AppEnvironment.TEST, cors_origins=["*"], _env_file=None)
    with pytest.raises(ValidationError, match="HTTP"):
        Settings(app_env=AppEnvironment.TEST, cors_origins=["file:///tmp/app"], _env_file=None)
    with pytest.raises(ValidationError, match="exact"):
        Settings(
            app_env=AppEnvironment.TEST,
            cors_origins=["https://app.example.test/path"],
            _env_file=None,
        )
