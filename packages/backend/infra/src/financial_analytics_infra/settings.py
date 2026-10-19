from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from ipaddress import ip_network
from urllib.parse import unquote, urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from financial_analytics_domain import EmailAddress

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


class LlmProvider(StrEnum):
    DISABLED = "disabled"
    OPENAI_COMPATIBLE = "openai_compatible"


class LlmEndpointScope(StrEnum):
    LOCAL = "local"
    EXTERNAL = "external"


class SmtpSecurity(StrEnum):
    PLAIN = "plain"
    STARTTLS = "starttls"
    TLS = "tls"


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
        hide_input_in_errors=True,
    )

    app_env: AppEnvironment = AppEnvironment.DEVELOPMENT
    app_name: str = "Financial Analytics API"
    app_version: str = "0.2.0"
    debug: bool = False
    log_level: str = "INFO"
    database_url_secret: SecretStr = Field(
        default=SecretStr(DEFAULT_DEVELOPMENT_DATABASE_URL),
        alias="DATABASE_URL",
        repr=False,
    )
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:4173", "http://127.0.0.1:4173"]
    )
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
    session_cookie_domain: str | None = None
    access_cookie_name: str = "fa_access"
    refresh_cookie_name: str = "fa_refresh"
    csrf_cookie_name: str = "fa_csrf"
    public_base_url: str = "http://localhost:4173"
    bootstrap_master_email: str | None = None
    trusted_proxy_ips: list[str] = Field(default_factory=list)
    smtp_host: str = "mailpit"
    smtp_port: int = Field(default=1025, ge=1, le=65535)
    smtp_from_address: str = "no-reply@localhost"
    smtp_security: SmtpSecurity = SmtpSecurity.PLAIN
    smtp_username: str | None = None
    smtp_password_value: SecretStr | None = Field(default=None, alias="SMTP_PASSWORD", repr=False)
    smtp_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    llm_provider: LlmProvider = LlmProvider.DISABLED
    llm_base_url: str | None = None
    llm_api_key_value: SecretStr | None = Field(default=None, alias="LLM_API_KEY", repr=False)
    llm_model: str = "Qwen/Qwen3-4B-AWQ"
    llm_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    llm_max_retries: int = Field(default=2, ge=0, le=3)
    llm_retry_backoff_seconds: float = Field(default=0.25, ge=0, le=5)
    llm_max_tokens: int = Field(default=800, ge=128, le=4096)
    llm_endpoint_scope: LlmEndpointScope = LlmEndpointScope.LOCAL
    llm_supports_json_schema: bool = True
    llm_supports_system_messages: bool = True
    llm_supports_non_thinking: bool = True
    test_clock_at: datetime | None = None

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

    @field_validator("public_base_url")
    @classmethod
    def validate_public_base_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        parsed = urlsplit(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("PUBLIC_BASE_URL must be an exact HTTP(S) origin")
        return normalized

    @field_validator("bootstrap_master_email", "smtp_from_address")
    @classmethod
    def validate_configured_email(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return EmailAddress(value).value

    @field_validator("smtp_username", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("smtp_password_value", "llm_api_key_value", mode="before")
    @classmethod
    def normalize_optional_secret(cls, value: object) -> object:
        if isinstance(value, str) and not value:
            return None
        return value

    @field_validator("session_cookie_domain")
    @classmethod
    def validate_cookie_domain(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip().lstrip(".").lower()
        if any(character in normalized for character in ("/", ":", "*", "@")):
            raise ValueError("SESSION_COOKIE_DOMAIN must be a bare DNS suffix")
        return normalized

    @field_validator("trusted_proxy_ips")
    @classmethod
    def validate_trusted_proxy_ips(cls, values: list[str]) -> list[str]:
        for value in values:
            try:
                network = ip_network(value.strip(), strict=False)
            except ValueError as error:
                raise ValueError(
                    "TRUSTED_PROXY_IPS must contain explicit IP addresses or CIDRs"
                ) from error
            if network.prefixlen == 0:
                raise ValueError("TRUSTED_PROXY_IPS cannot trust every address")
        return [value.strip() for value in values]

    @field_validator("llm_base_url")
    @classmethod
    def validate_llm_base_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.rstrip("/")
        parsed = urlsplit(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("LLM_BASE_URL must be an HTTP(S) URL without credentials or query")
        return normalized

    @model_validator(mode="after")
    def protect_production(self) -> Settings:
        if self.test_clock_at is not None:
            if self.app_env is not AppEnvironment.TEST:
                raise ValueError("TEST_CLOCK_AT is allowed only when APP_ENV=test")
            if self.test_clock_at.tzinfo is None or self.test_clock_at.utcoffset() is None:
                raise ValueError("TEST_CLOCK_AT must include a UTC offset")
        if self.llm_provider is LlmProvider.OPENAI_COMPATIBLE:
            if self.llm_base_url is None:
                raise ValueError("openai_compatible LLM provider requires LLM_BASE_URL")
            if not self.llm_model.strip():
                raise ValueError("openai_compatible LLM provider requires LLM_MODEL")
        if (self.smtp_username is None) != (self.smtp_password_value is None):
            raise ValueError("SMTP_USERNAME and SMTP_PASSWORD must be configured together")
        if self.app_env is AppEnvironment.PRODUCTION:
            if (
                self.database_url == DEFAULT_DEVELOPMENT_DATABASE_URL
                or "financial_analytics_dev" in self.database_url
                or "replace-with" in self.database_url
            ):
                raise ValueError("production requires an explicit DATABASE_URL")
            database_password = unquote(urlsplit(self.database_url).password or "")
            if (
                len(database_password) < 16
                or len(set(database_password)) < 8
                or database_password.lower()
                in {"postgres", "password", "secret", "admin", "changeme"}
            ):
                raise ValueError("production requires non-default database credentials")
            if self.debug or self.log_level == "DEBUG":
                raise ValueError("production forbids debug mode and DEBUG logging")
            if not self.session_cookie_secure:
                raise ValueError("production requires Secure session cookies")
            if urlsplit(self.public_base_url).scheme != "https":
                raise ValueError("production PUBLIC_BASE_URL must use HTTPS")
            if any(urlsplit(origin).scheme != "https" for origin in self.cors_origins):
                raise ValueError("production CORS origins must use HTTPS")
            if not self.trusted_proxy_ips:
                raise ValueError("production requires explicit TRUSTED_PROXY_IPS")
            if self.bootstrap_master_email is None:
                raise ValueError("production requires BOOTSTRAP_MASTER_EMAIL")
            if not self.smtp_host.strip() or self.smtp_from_address is None:
                raise ValueError("production requires SMTP host and from address")
            if self.smtp_security is SmtpSecurity.PLAIN:
                raise ValueError("production SMTP requires STARTTLS or TLS")
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
            if any(
                any(
                    marker in secret.lower()
                    for marker in (
                        "replace-with-",
                        "default",
                        "change-me",
                        "changeme",
                        "development",
                    )
                )
                for secret in configured_secrets
            ):
                raise ValueError("production identity secrets still contain placeholders")
            if len(configured_secrets) != 3:
                raise ValueError("production identity secrets must be independent")
            if any(len(set(secret)) < 12 for secret in configured_secrets):
                raise ValueError("production identity secrets are too predictable")
            if (
                self.llm_provider is LlmProvider.OPENAI_COMPATIBLE
                and self.llm_endpoint_scope is LlmEndpointScope.EXTERNAL
            ):
                assert self.llm_base_url is not None
                if urlsplit(self.llm_base_url).scheme != "https":
                    raise ValueError("production external LLM endpoint requires HTTPS")
                if self.llm_api_key_value is None:
                    raise ValueError("production external LLM endpoint requires LLM_API_KEY")
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

    @property
    def llm_api_key(self) -> str | None:
        if self.llm_api_key_value is None:
            return None
        return self.llm_api_key_value.get_secret_value()

    @property
    def smtp_password(self) -> str | None:
        if self.smtp_password_value is None:
            return None
        return self.smtp_password_value.get_secret_value()
