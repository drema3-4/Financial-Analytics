from __future__ import annotations

from enum import StrEnum

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DEVELOPMENT_DATABASE_URL = (
    "postgresql+psycopg://financial_analytics:financial_analytics_dev"
    "@localhost:5432/financial_analytics"
)


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
        return origins

    @model_validator(mode="after")
    def protect_production(self) -> Settings:
        if self.app_env is AppEnvironment.PRODUCTION:
            if self.database_url == DEFAULT_DEVELOPMENT_DATABASE_URL:
                raise ValueError("production requires an explicit DATABASE_URL")
            if "*" in self.cors_origins:
                raise ValueError("production cannot use a wildcard CORS origin")
        return self

    @property
    def database_url(self) -> str:
        return self.database_url_secret.get_secret_value()
