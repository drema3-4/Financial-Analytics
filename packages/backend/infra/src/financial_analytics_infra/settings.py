from __future__ import annotations

from enum import StrEnum
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DEVELOPMENT_DATABASE_URL = (
    "postgresql+psycopg://financial_analytics:financial_analytics_dev"
    "@localhost:5432/financial_analytics"
)
DEFAULT_DEVELOPMENT_SESSION_SECRET = "development-session-key-change-me-0001"
DEFAULT_DEVELOPMENT_CSRF_SECRET = "development-csrf-key-change-me-now-0001"
DEFAULT_DEVELOPMENT_EMAIL_TOKEN_SECRET = "development-email-key-change-me-now-0001"


class AppEnvironment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Validated runtime configuration loaded from environment variables.

    Secret-bearing values use ``SecretStr`` so accidental repr/logging does not reveal them.
    Production rejects development defaults and wildcard browser origins.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    app_env: AppEnvironment = AppEnvironment.DEVELOPMENT
    app_name: str = "Financial Analytics API"
    app_version: str = "0.1.0"
    log_level: str = "INFO"
    database_url_secret: SecretStr = Field(
        default=SecretStr(DEFAULT_DEVELOPMENT_DATABASE_URL),
        alias="DATABASE_URL",
        repr=False,
    )
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:4173"])
    session_secret_value: SecretStr = Field(
        default=SecretStr(DEFAULT_DEVELOPMENT_SESSION_SECRET),
        alias="SESSION_SECRET",
        repr=False,
    )
    csrf_secret_value: SecretStr = Field(
        default=SecretStr(DEFAULT_DEVELOPMENT_CSRF_SECRET),
        alias="CSRF_SECRET",
        repr=False,
    )
    email_token_secret_value: SecretStr = Field(
        default=SecretStr(DEFAULT_DEVELOPMENT_EMAIL_TOKEN_SECRET),
        alias="EMAIL_TOKEN_SECRET",
        repr=False,
    )
    session_cookie_secure: bool = True
    access_cookie_name: str = "fa_access"
    refresh_cookie_name: str = "fa_refresh"
    csrf_cookie_name: str = "fa_csrf"

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if normalized not in allowed:
            msg = f"log_level must be one of {sorted(allowed)}"
            raise ValueError(msg)
        return normalized

    @field_validator("cors_origins")
    @classmethod
    def validate_origins(cls, origins: list[str]) -> list[str]:
        if not origins:
            raise ValueError("cors_origins must contain at least one trusted origin")
        if any("*" in origin for origin in origins):
            raise ValueError("wildcard CORS origins are forbidden")
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise ValueError("CORS origins must be exact HTTP(S) origins")
        return origins

    @field_validator("session_secret_value", "csrf_secret_value", "email_token_secret_value")
    @classmethod
    def validate_secret_length(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().encode("utf-8")) < 32:
            raise ValueError("identity secrets must contain at least 32 UTF-8 bytes")
        return value

    @model_validator(mode="after")
    def protect_production(self) -> Settings:
        if self.app_env is AppEnvironment.PRODUCTION:
            if self.database_url == DEFAULT_DEVELOPMENT_DATABASE_URL:
                raise ValueError("production requires an explicit DATABASE_URL")
            if not self.session_cookie_secure:
                raise ValueError("production requires Secure session cookies")
            development_secrets = {
                DEFAULT_DEVELOPMENT_SESSION_SECRET,
                DEFAULT_DEVELOPMENT_CSRF_SECRET,
                DEFAULT_DEVELOPMENT_EMAIL_TOKEN_SECRET,
            }
            configured_secrets = {
                self.session_secret,
                self.csrf_secret,
                self.email_token_secret,
            }
            if development_secrets & configured_secrets:
                raise ValueError("production requires explicit identity secrets")
            if any(secret.startswith("replace-with-") for secret in configured_secrets):
                raise ValueError("production identity secrets still contain placeholders")
        return self

    @property
    def database_url(self) -> str:
        return self.database_url_secret.get_secret_value()

    @property
    def session_secret(self) -> str:
        return self.session_secret_value.get_secret_value()

    @property
    def csrf_secret(self) -> str:
        return self.csrf_secret_value.get_secret_value()

    @property
    def email_token_secret(self) -> str:
        return self.email_token_secret_value.get_secret_value()
