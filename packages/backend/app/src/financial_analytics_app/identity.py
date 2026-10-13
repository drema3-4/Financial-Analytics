from __future__ import annotations

import hmac
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol
from uuid import UUID, uuid4

from financial_analytics_domain import (
    Currency,
    EmailAddress,
    EmailToken,
    EmailTokenPurpose,
    Instant,
    Invitation,
    UserProfile,
    UserStatus,
)


class IdentityError(Exception):
    """Base class for expected identity failures safe to translate at the HTTP edge."""


class BootstrapClosedError(IdentityError):
    pass


class InvalidCredentialsError(IdentityError):
    pass


class InvalidSessionError(IdentityError):
    pass


class CsrfValidationError(IdentityError):
    pass


class DisabledUserError(IdentityError):
    pass


class RateLimitExceededError(IdentityError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("rate limit exceeded")
        self.retry_after_seconds = retry_after_seconds


class EmailNotAllowedError(IdentityError):
    pass


class EmailTokenInvalidError(IdentityError):
    pass


@dataclass(frozen=True, slots=True)
class AuthenticationRecord:
    profile: UserProfile
    password_hash: str


@dataclass(frozen=True, slots=True)
class SessionRecord:
    id: UUID
    owner_id: UUID
    access_hash: str
    refresh_hash: str
    csrf_hash: str
    access_expires_at: Instant
    refresh_expires_at: Instant
    created_at: Instant
    rotated_at: Instant
    revoked_at: Instant | None = None


@dataclass(frozen=True, slots=True)
class SessionTokens:
    profile: UserProfile
    access_token: str
    refresh_token: str
    csrf_token: str
    access_expires_at: Instant
    refresh_expires_at: Instant


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    profile: UserProfile
    session_id: UUID
    csrf_hash: str


@dataclass(frozen=True, slots=True)
class AllowlistEntry:
    id: UUID
    email: EmailAddress
    added_by: UUID
    created_at: Instant
    revoked_at: Instant | None = None


class PasswordHashProvider(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password_hash: str, password: str) -> bool: ...

    def needs_rehash(self, password_hash: str) -> bool: ...


class SecretProvider(Protocol):
    def generate(self) -> str: ...

    def digest(self, secret: str) -> str: ...


class RateLimiter(Protocol):
    def consume(self, key: str, *, limit: int, window: timedelta, now: Instant) -> int | None:
        """Return retry-after seconds when denied, otherwise None."""


class IdentityStore(Protocol):
    def create_master(
        self,
        *,
        profile: UserProfile,
        password_hash: str,
        request_id: UUID | None,
    ) -> None: ...

    def get_authentication(self, email: EmailAddress) -> AuthenticationRecord | None: ...

    def get_profile(self, user_id: UUID) -> UserProfile | None: ...

    def replace_password_hash(self, user_id: UUID, password_hash: str, now: Instant) -> None: ...

    def create_session(
        self,
        session: SessionRecord,
        *,
        event_type: str,
        request_id: UUID | None,
    ) -> None: ...

    def get_session(self, session_id: UUID) -> SessionRecord | None: ...

    def rotate_session(
        self,
        session_id: UUID,
        *,
        expected_refresh_hash: str,
        access_hash: str,
        refresh_hash: str,
        csrf_hash: str,
        access_expires_at: Instant,
        rotated_at: Instant,
        request_id: UUID | None,
    ) -> SessionRecord | None: ...

    def revoke_session(
        self, session_id: UUID, *, now: Instant, request_id: UUID | None
    ) -> bool: ...

    def revoke_all_sessions(
        self, owner_id: UUID, *, now: Instant, request_id: UUID | None
    ) -> int: ...

    def add_allowlist_entry(self, entry: AllowlistEntry, *, request_id: UUID | None) -> None: ...

    def is_email_allowed(self, email: EmailAddress) -> bool: ...

    def create_invitation(
        self,
        invitation: Invitation,
        token: EmailToken,
        *,
        request_id: UUID | None,
    ) -> None: ...

    def create_email_token(
        self, token: EmailToken, *, actor_id: UUID, request_id: UUID | None
    ) -> None: ...

    def consume_email_token(
        self,
        token_id: UUID,
        token_hash: str,
        purpose: EmailTokenPurpose,
        *,
        now: Instant,
        request_id: UUID | None,
    ) -> EmailToken | None: ...


def validate_password(password: str) -> None:
    if len(password) < 12:
        raise ValueError("password must contain at least 12 characters")
    if len(password) > 1024:
        raise ValueError("password is too long")


class AuthService:
    ACCESS_TTL = timedelta(minutes=15)
    REFRESH_TTL = timedelta(days=30)
    LOGIN_LIMIT = 5
    LOGIN_IP_LIMIT = 20
    REFRESH_LIMIT = 30
    REFRESH_IP_LIMIT = 60
    RATE_WINDOW = timedelta(minutes=1)

    def __init__(
        self,
        store: IdentityStore,
        password_hashes: PasswordHashProvider,
        session_secrets: SecretProvider,
        csrf_secrets: SecretProvider,
        rate_limiter: RateLimiter,
        *,
        clock: Callable[[], Instant] = Instant.now,
        uuid_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._store = store
        self._password_hashes = password_hashes
        self._session_secrets = session_secrets
        self._csrf_secrets = csrf_secrets
        self._rate_limiter = rate_limiter
        self._clock = clock
        self._uuid_factory = uuid_factory
        self._dummy_password_hash = password_hashes.hash(session_secrets.generate())

    def bootstrap_master(
        self,
        *,
        email: str,
        password: str,
        base_currency: str,
        locale: str,
        timezone: str,
        request_id: UUID | None = None,
    ) -> SessionTokens:
        validate_password(password)
        now = self._clock()
        profile = UserProfile(
            id=self._uuid_factory(),
            email=EmailAddress(email),
            base_currency=Currency(base_currency),
            locale=locale,
            timezone=timezone,
            status=UserStatus.ACTIVE,
            is_master=True,
            created_at=now,
        )
        password_hash = self._password_hashes.hash(password)
        self._store.create_master(
            profile=profile,
            password_hash=password_hash,
            request_id=request_id,
        )
        return self._new_session(
            profile, now=now, event_type="identity.bootstrap_completed", request_id=request_id
        )

    def login(
        self,
        email: str,
        password: str,
        *,
        rate_limit_key: str,
        request_id: UUID | None = None,
    ) -> SessionTokens:
        now = self._clock()
        normalized = EmailAddress(email)
        self._enforce_rate_limit(f"login:ip:{rate_limit_key}", self.LOGIN_IP_LIMIT, now)
        self._enforce_rate_limit(f"login:identity:{normalized.value}", self.LOGIN_LIMIT, now)
        if len(password) > 1024:
            raise InvalidCredentialsError("invalid email or password")
        record = self._store.get_authentication(normalized)
        candidate_hash = self._dummy_password_hash if record is None else record.password_hash
        password_is_valid = self._password_hashes.verify(candidate_hash, password)
        if record is None or not password_is_valid:
            raise InvalidCredentialsError("invalid email or password")
        if not record.profile.enabled:
            raise DisabledUserError("user is disabled")
        if self._password_hashes.needs_rehash(record.password_hash):
            self._store.replace_password_hash(
                record.profile.id, self._password_hashes.hash(password), now
            )
        return self._new_session(
            record.profile,
            now=now,
            event_type="identity.login_succeeded",
            request_id=request_id,
        )

    def authenticate_access(self, raw_token: str) -> AuthenticatedSession:
        session_id, secret = _parse_opaque_token(raw_token)
        session = self._store.get_session(session_id)
        now = self._clock()
        if (
            session is None
            or session.revoked_at is not None
            or session.access_expires_at.value <= now.value
            or not hmac.compare_digest(session.access_hash, self._session_secrets.digest(secret))
        ):
            raise InvalidSessionError("access session is invalid")
        profile = self._store.get_profile(session.owner_id)
        if profile is None:
            raise InvalidSessionError("access session is invalid")
        if not profile.enabled:
            raise DisabledUserError("user is disabled")
        return AuthenticatedSession(
            profile=profile, session_id=session.id, csrf_hash=session.csrf_hash
        )

    def verify_csrf(
        self,
        authenticated: AuthenticatedSession,
        *,
        cookie_token: str | None,
        header_token: str | None,
    ) -> None:
        if (
            cookie_token is None
            or header_token is None
            or not hmac.compare_digest(cookie_token, header_token)
            or not hmac.compare_digest(
                authenticated.csrf_hash, self._csrf_secrets.digest(header_token)
            )
        ):
            raise CsrfValidationError("CSRF token is invalid")

    def refresh(
        self,
        raw_refresh_token: str,
        *,
        csrf_cookie: str | None,
        csrf_header: str | None,
        rate_limit_key: str,
        request_id: UUID | None = None,
    ) -> SessionTokens:
        now = self._clock()
        session_id, secret = _parse_opaque_token(raw_refresh_token)
        self._enforce_rate_limit(f"refresh:ip:{rate_limit_key}", self.REFRESH_IP_LIMIT, now)
        self._enforce_rate_limit(f"refresh:session:{session_id}", self.REFRESH_LIMIT, now)
        current = self._store.get_session(session_id)
        if (
            current is None
            or current.revoked_at is not None
            or current.refresh_expires_at.value <= now.value
        ):
            raise InvalidSessionError("refresh session is invalid")
        if (
            csrf_cookie is None
            or csrf_header is None
            or not hmac.compare_digest(csrf_cookie, csrf_header)
            or not hmac.compare_digest(current.csrf_hash, self._csrf_secrets.digest(csrf_header))
        ):
            raise CsrfValidationError("CSRF token is invalid")
        profile = self._store.get_profile(current.owner_id)
        if profile is None:
            raise InvalidSessionError("refresh session is invalid")
        if not profile.enabled:
            raise DisabledUserError("user is disabled")
        presented_hash = self._session_secrets.digest(secret)
        access_secret = self._session_secrets.generate()
        refresh_secret = self._session_secrets.generate()
        csrf_secret = self._csrf_secrets.generate()
        rotated = self._store.rotate_session(
            session_id,
            expected_refresh_hash=presented_hash,
            access_hash=self._session_secrets.digest(access_secret),
            refresh_hash=self._session_secrets.digest(refresh_secret),
            csrf_hash=self._csrf_secrets.digest(csrf_secret),
            access_expires_at=Instant(now.value + self.ACCESS_TTL),
            rotated_at=now,
            request_id=request_id,
        )
        if rotated is None:
            raise InvalidSessionError("refresh session is invalid")
        return SessionTokens(
            profile=profile,
            access_token=_format_opaque_token(session_id, access_secret),
            refresh_token=_format_opaque_token(session_id, refresh_secret),
            csrf_token=csrf_secret,
            access_expires_at=rotated.access_expires_at,
            refresh_expires_at=rotated.refresh_expires_at,
        )

    def logout_current(
        self,
        authenticated: AuthenticatedSession,
        *,
        csrf_cookie: str | None,
        csrf_header: str | None,
        request_id: UUID | None = None,
    ) -> None:
        self.verify_csrf(authenticated, cookie_token=csrf_cookie, header_token=csrf_header)
        self._store.revoke_session(
            authenticated.session_id, now=self._clock(), request_id=request_id
        )

    def logout_all(
        self,
        authenticated: AuthenticatedSession,
        *,
        csrf_cookie: str | None,
        csrf_header: str | None,
        request_id: UUID | None = None,
    ) -> int:
        self.verify_csrf(authenticated, cookie_token=csrf_cookie, header_token=csrf_header)
        return self._store.revoke_all_sessions(
            authenticated.profile.id, now=self._clock(), request_id=request_id
        )

    def _new_session(
        self,
        profile: UserProfile,
        *,
        now: Instant,
        event_type: str,
        request_id: UUID | None,
    ) -> SessionTokens:
        session_id = self._uuid_factory()
        access_secret = self._session_secrets.generate()
        refresh_secret = self._session_secrets.generate()
        csrf_secret = self._csrf_secrets.generate()
        session = SessionRecord(
            id=session_id,
            owner_id=profile.id,
            access_hash=self._session_secrets.digest(access_secret),
            refresh_hash=self._session_secrets.digest(refresh_secret),
            csrf_hash=self._csrf_secrets.digest(csrf_secret),
            access_expires_at=Instant(now.value + self.ACCESS_TTL),
            refresh_expires_at=Instant(now.value + self.REFRESH_TTL),
            created_at=now,
            rotated_at=now,
        )
        self._store.create_session(session, event_type=event_type, request_id=request_id)
        return SessionTokens(
            profile=profile,
            access_token=_format_opaque_token(session_id, access_secret),
            refresh_token=_format_opaque_token(session_id, refresh_secret),
            csrf_token=csrf_secret,
            access_expires_at=session.access_expires_at,
            refresh_expires_at=session.refresh_expires_at,
        )

    def _enforce_rate_limit(self, key: str, limit: int, now: Instant) -> None:
        retry_after = self._rate_limiter.consume(key, limit=limit, window=self.RATE_WINDOW, now=now)
        if retry_after is not None:
            raise RateLimitExceededError(retry_after)


class InvitationService:
    TOKEN_TTL = timedelta(hours=24)

    def __init__(
        self,
        store: IdentityStore,
        token_secrets: SecretProvider,
        *,
        clock: Callable[[], Instant] = Instant.now,
        uuid_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._store = store
        self._token_secrets = token_secrets
        self._clock = clock
        self._uuid_factory = uuid_factory

    def allow_email(
        self, email: str, *, actor_id: UUID, request_id: UUID | None = None
    ) -> AllowlistEntry:
        entry = AllowlistEntry(
            id=self._uuid_factory(),
            email=EmailAddress(email),
            added_by=actor_id,
            created_at=self._clock(),
        )
        self._store.add_allowlist_entry(entry, request_id=request_id)
        return entry

    def issue_invitation(
        self, email: str, *, actor_id: UUID, request_id: UUID | None = None
    ) -> tuple[Invitation, str]:
        normalized = EmailAddress(email)
        if not self._store.is_email_allowed(normalized):
            raise EmailNotAllowedError("email is not on the allowlist")
        now = self._clock()
        invitation = Invitation(
            id=self._uuid_factory(),
            email=normalized,
            invited_by=actor_id,
            created_at=now,
            expires_at=Instant(now.value + self.TOKEN_TTL),
        )
        secret = self._token_secrets.generate()
        token = EmailToken(
            id=self._uuid_factory(),
            purpose=EmailTokenPurpose.INVITATION,
            token_hash=self._token_secrets.digest(secret),
            invitation_id=invitation.id,
            created_at=now,
            expires_at=invitation.expires_at,
        )
        self._store.create_invitation(invitation, token, request_id=request_id)
        return invitation, _format_opaque_token(token.id, secret)

    def consume_invitation(self, raw_token: str, *, request_id: UUID | None = None) -> EmailToken:
        return self._consume(raw_token, EmailTokenPurpose.INVITATION, request_id=request_id)

    def issue_user_token(
        self,
        user_id: UUID,
        purpose: EmailTokenPurpose,
        *,
        actor_id: UUID,
        request_id: UUID | None = None,
    ) -> tuple[EmailToken, str]:
        if purpose is EmailTokenPurpose.INVITATION:
            raise ValueError("invitation tokens require an invitation subject")
        if self._store.get_profile(user_id) is None:
            raise ValueError("email token user does not exist")
        now = self._clock()
        secret = self._token_secrets.generate()
        token = EmailToken(
            id=self._uuid_factory(),
            purpose=purpose,
            token_hash=self._token_secrets.digest(secret),
            user_id=user_id,
            created_at=now,
            expires_at=Instant(now.value + self.TOKEN_TTL),
        )
        self._store.create_email_token(token, actor_id=actor_id, request_id=request_id)
        return token, _format_opaque_token(token.id, secret)

    def consume_user_token(
        self,
        raw_token: str,
        purpose: EmailTokenPurpose,
        *,
        request_id: UUID | None = None,
    ) -> EmailToken:
        if purpose is EmailTokenPurpose.INVITATION:
            raise ValueError("use consume_invitation for invitation tokens")
        return self._consume(raw_token, purpose, request_id=request_id)

    def _consume(
        self,
        raw_token: str,
        purpose: EmailTokenPurpose,
        *,
        request_id: UUID | None,
    ) -> EmailToken:
        try:
            token_id, secret = _parse_opaque_token(raw_token)
        except InvalidSessionError as error:
            raise EmailTokenInvalidError(
                "email token is invalid, expired, or already consumed"
            ) from error
        consumed = self._store.consume_email_token(
            token_id,
            self._token_secrets.digest(secret),
            purpose,
            now=self._clock(),
            request_id=request_id,
        )
        if consumed is None:
            raise EmailTokenInvalidError("email token is invalid, expired, or already consumed")
        return consumed


def _format_opaque_token(token_id: UUID, secret: str) -> str:
    return f"{token_id}.{secret}"


def _parse_opaque_token(raw_token: str) -> tuple[UUID, str]:
    try:
        raw_id, secret = raw_token.split(".", maxsplit=1)
        token_id = UUID(raw_id)
    except (ValueError, AttributeError) as error:
        raise InvalidSessionError("token format is invalid") from error
    if len(secret) < 32:
        raise InvalidSessionError("token format is invalid")
    return token_id, secret
