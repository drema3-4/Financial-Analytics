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
