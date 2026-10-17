from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from financial_analytics_app.identity import (
    AccessManagementDeniedError,
    AuthService,
    BootstrapClosedError,
    CsrfValidationError,
    DisabledUserError,
    EmailNotAllowedError,
    EmailTokenInvalidError,
    InvalidCredentialsError,
    InvalidSessionError,
    InvitationService,
    RateLimitExceededError,
    SessionTokens,
)
from financial_analytics_domain import EmailAddress, EmailTokenPurpose, Instant, UserStatus
from financial_analytics_infra.security import (
    Argon2idPasswordHashes,
    HmacSecretProvider,
    InMemorySlidingWindowRateLimiter,
)
from tests.fakes_identity import FakeIdentityStore, FakePasswordHashes, MutableClock

SESSION_KEY = "s" * 32
CSRF_KEY = "c" * 32
EMAIL_KEY = "e" * 32


def auth_service(
    store: FakeIdentityStore | None = None, clock: MutableClock | None = None
) -> tuple[AuthService, FakeIdentityStore, MutableClock]:
    selected_store = store or FakeIdentityStore()
    selected_clock = clock or MutableClock()
    return (
        AuthService(
            selected_store,
            FakePasswordHashes(),
            HmacSecretProvider(SESSION_KEY),
            HmacSecretProvider(CSRF_KEY),
            InMemorySlidingWindowRateLimiter(),
            clock=selected_clock,
        ),
        selected_store,
        selected_clock,
    )


def bootstrap(service: AuthService) -> SessionTokens:
    return service.bootstrap_master(
        email=" Master@Example.COM ",
        password="correct horse battery staple",
        base_currency="RUB",
        locale="ru-RU",
        timezone="Europe/Saratov",
    )


def test_email_profile_validation_and_normalization() -> None:
    assert EmailAddress(" Test@Example.COM ").value == "test@example.com"
    with pytest.raises(ValueError, match="valid address"):
        EmailAddress("not-an-email")

    service, _, _ = auth_service()
    with pytest.raises(ValueError, match="IANA"):
        service.bootstrap_master(
            email="master@example.com",
            password="correct horse battery staple",
            base_currency="RUB",
            locale="ru-RU",
            timezone="Mars/Olympus",
        )
    with pytest.raises(ValueError, match="at least 12"):
        service.bootstrap_master(
            email="master@example.com",
            password="too-short",
            base_currency="RUB",
            locale="ru-RU",
            timezone="UTC",
        )


def test_argon2id_hashes_password_and_never_embeds_plaintext() -> None:
    provider = Argon2idPasswordHashes()
    password = "correct horse battery staple"
    encoded = provider.hash(password)

    assert encoded.startswith("$argon2id$")
    assert password not in encoded
    assert provider.verify(encoded, password)
    assert not provider.verify(encoded, "wrong password")
    assert not provider.verify("not-a-valid-hash", password)
    assert provider.needs_rehash("not-a-valid-hash")
    assert not provider.needs_rehash(encoded)


def test_bootstrap_is_one_time_and_persists_only_password_hash() -> None:
    service, store, _ = auth_service()
    tokens = bootstrap(service)

    record = store.auth_by_email["master@example.com"]
    assert record.password_hash == "hashed::correct horse battery staple"
    assert record.profile.id == tokens.profile.id
    assert record.profile.is_master
    with pytest.raises(BootstrapClosedError):
        bootstrap(service)


def test_login_access_csrf_logout_and_disabled_user_matrix() -> None:
    service, store, _ = auth_service()
    initial = bootstrap(service)

    with pytest.raises(InvalidCredentialsError):
        service.login("unknown@example.com", "wrong password", rate_limit_key="127.0.0.1")
    logged_in = service.login(
        "MASTER@example.com",
        "correct horse battery staple",
        rate_limit_key="127.0.0.1",
    )
    authenticated = service.authenticate_access(logged_in.access_token)
    assert authenticated.profile.id == initial.profile.id

    with pytest.raises(CsrfValidationError):
        service.logout_current(authenticated, csrf_cookie=logged_in.csrf_token, csrf_header="wrong")
    service.logout_current(
        authenticated,
        csrf_cookie=logged_in.csrf_token,
        csrf_header=logged_in.csrf_token,
    )
    with pytest.raises(InvalidSessionError):
        service.authenticate_access(logged_in.access_token)

    profile = replace(initial.profile, status=UserStatus.DISABLED)
    store.profiles[profile.id] = profile
    old = store.auth_by_email[profile.email.value]
    store.auth_by_email[profile.email.value] = replace(old, profile=profile)
    with pytest.raises(DisabledUserError):
        service.login(
            profile.email.value,
            "correct horse battery staple",
            rate_limit_key="disabled-client",
        )
    with pytest.raises(DisabledUserError):
        service.authenticate_access(initial.access_token)


def test_access_expiry_refresh_rotation_replay_and_logout_all() -> None:
    service, store, clock = auth_service()
    first = bootstrap(service)
    clock.value = Instant(clock.value.value + AuthService.ACCESS_TTL + timedelta(seconds=1))
    with pytest.raises(InvalidSessionError):
        service.authenticate_access(first.access_token)

    rotated = service.refresh(
        first.refresh_token,
        csrf_cookie=first.csrf_token,
        csrf_header=first.csrf_token,
        rate_limit_key="client",
    )
    assert rotated.refresh_token != first.refresh_token
    assert service.authenticate_access(rotated.access_token).profile.id == first.profile.id

    with pytest.raises(InvalidSessionError):
        service.refresh(
            first.refresh_token,
            csrf_cookie=rotated.csrf_token,
            csrf_header=rotated.csrf_token,
            rate_limit_key="client",
        )
    with pytest.raises(InvalidSessionError):
        service.authenticate_access(rotated.access_token)

    current = service.login(
        first.profile.email.value,
        "correct horse battery staple",
        rate_limit_key="logout-client",
    )
    authenticated = service.authenticate_access(current.access_token)
    assert (
        service.logout_all(
            authenticated,
            csrf_cookie=current.csrf_token,
            csrf_header=current.csrf_token,
        )
        >= 1
    )
    assert all(item.revoked_at is not None for item in store.sessions.values())


def test_refresh_rejects_bad_csrf_expired_and_malformed_tokens() -> None:
    service, store, clock = auth_service()
    tokens = bootstrap(service)
    with pytest.raises(CsrfValidationError):
        service.refresh(
            tokens.refresh_token,
            csrf_cookie=tokens.csrf_token,
            csrf_header=None,
            rate_limit_key="client",
        )
    with pytest.raises(InvalidSessionError):
        service.authenticate_access("malformed")

    session_id = next(iter(store.sessions))
    current = store.sessions[session_id]
    store.sessions[session_id] = replace(
        current, refresh_expires_at=Instant(clock.value.value - timedelta(seconds=1))
    )
    with pytest.raises(InvalidSessionError):
        service.refresh(
            tokens.refresh_token,
            csrf_cookie=tokens.csrf_token,
            csrf_header=tokens.csrf_token,
            rate_limit_key="client",
        )


def test_login_rate_limit_is_keyed_and_returns_retry_after() -> None:
    service, _, _ = auth_service()
    bootstrap(service)
    for _ in range(AuthService.LOGIN_LIMIT):
        with pytest.raises(InvalidCredentialsError):
            service.login("master@example.com", "wrong", rate_limit_key="same-client")
    with pytest.raises(RateLimitExceededError) as raised:
        service.login("master@example.com", "wrong", rate_limit_key="same-client")
    assert raised.value.retry_after_seconds == 60


def test_invitation_requires_allowlist_and_token_is_one_time_with_ttl() -> None:
    service, store, clock = auth_service()
    master = bootstrap(service).profile
    invitations = InvitationService(
        store,
        HmacSecretProvider(EMAIL_KEY),
        clock=clock,
    )
    with pytest.raises(EmailNotAllowedError):
        invitations.issue_invitation("guest@example.com", actor_id=master.id)

    invitations.allow_email("Guest@Example.com", actor_id=master.id)
    invitation, raw_token = invitations.issue_invitation("guest@example.com", actor_id=master.id)
    digest = next(iter(store.tokens))
    assert raw_token not in digest
    assert store.tokens[digest].token_hash == digest
    consumed = invitations.consume_invitation(raw_token)
    assert consumed.invitation_id == invitation.id
    with pytest.raises(EmailTokenInvalidError):
        invitations.consume_invitation(raw_token)
    with pytest.raises(EmailTokenInvalidError):
        invitations.consume_invitation("malformed")

    _, expiring_token = invitations.issue_invitation("guest@example.com", actor_id=master.id)
    clock.value = Instant(clock.value.value + timedelta(hours=25))
    with pytest.raises(EmailTokenInvalidError):
        invitations.consume_invitation(expiring_token)

    clock.value = Instant(clock.value.value - timedelta(hours=25))
    email_token, raw_user_token = invitations.issue_user_token(
        master.id,
        EmailTokenPurpose.VERIFY_EMAIL,
        actor_id=master.id,
    )
    assert (
        invitations.consume_user_token(raw_user_token, EmailTokenPurpose.VERIFY_EMAIL).id
        == email_token.id
    )
    with pytest.raises(EmailTokenInvalidError):
        invitations.consume_user_token(raw_user_token, EmailTokenPurpose.VERIFY_EMAIL)
    with pytest.raises(ValueError, match="invitation subject"):
        invitations.issue_user_token(
            master.id,
            EmailTokenPurpose.INVITATION,
            actor_id=master.id,
        )


def test_invitation_acceptance_roles_replay_and_password_reset_are_audited() -> None:
    service, store, clock = auth_service()
    master = bootstrap(service).profile
    invitations = InvitationService(
        store,
        HmacSecretProvider(EMAIL_KEY),
        FakePasswordHashes(),
        public_base_url="https://finance.example.test",
        clock=clock,
    )
    invitations.allow_email("admin@example.com", actor_id=master.id)
    invitation, raw_token = invitations.issue_invitation(
        "admin@example.com", actor_id=master.id, is_admin=True
    )

    assert invitation.expires_at.value - invitation.created_at.value == timedelta(hours=2)
    assert len(store.email_jobs) == 1
    assert raw_token in (store.email_jobs[0].text_body or "")
    accepted = invitations.accept_invitation(
        raw_token,
        password="another correct horse battery",
        base_currency="RUB",
        locale="ru-RU",
        timezone="Europe/Saratov",
    )
    assert accepted.email.value == "admin@example.com"
    assert accepted.is_admin
    assert accepted.email_verified_at == clock()
    with pytest.raises(EmailTokenInvalidError):
        invitations.accept_invitation(
            raw_token,
            password="another correct horse battery",
            base_currency="RUB",
            locale="ru-RU",
            timezone="Europe/Saratov",
        )
    assert any(event == "identity.email_token_replay_rejected" for event, _ in store.audit)

    before_unknown_request = len(store.email_jobs)
    invitations.request_password_reset("missing@example.com")
    assert len(store.email_jobs) == before_unknown_request
    reset_token, raw_reset = invitations.issue_user_token(
        accepted.id,
        EmailTokenPurpose.RESET_PASSWORD,
        actor_id=accepted.id,
    )
    assert reset_token.expires_at.value - reset_token.created_at.value == timedelta(minutes=15)
    invitations.reset_password(raw_reset, new_password="fresh correct horse battery")
    assert store.auth_by_email[accepted.email.value].password_hash == (
        "hashed::fresh correct horse battery"
    )
    with pytest.raises(EmailTokenInvalidError):
        invitations.reset_password(raw_reset, new_password="fresh correct horse battery")


def test_only_master_or_admin_can_manage_access_and_only_master_grants_admin() -> None:
    service, store, clock = auth_service()
    master = bootstrap(service).profile
    invitations = InvitationService(
        store,
        HmacSecretProvider(EMAIL_KEY),
        FakePasswordHashes(),
        clock=clock,
    )
    member = replace(master, id=master.id.__class__(int=2), is_master=False, is_admin=False)
    store.profiles[member.id] = member
    with pytest.raises(AccessManagementDeniedError):
        invitations.allow_email("new@example.com", actor_id=member.id)

    admin = replace(master, id=master.id.__class__(int=3), is_master=False, is_admin=True)
    store.profiles[admin.id] = admin
    invitations.allow_email("new@example.com", actor_id=admin.id)
    with pytest.raises(AccessManagementDeniedError):
        invitations.issue_invitation("new@example.com", actor_id=admin.id, is_admin=True)


def test_sliding_window_limiter_expires_old_events_and_validates_configuration() -> None:
    limiter = InMemorySlidingWindowRateLimiter()
    clock = MutableClock()
    assert limiter.consume("key", limit=1, window=timedelta(seconds=10), now=clock()) is None
    assert limiter.consume("key", limit=1, window=timedelta(seconds=10), now=clock()) == 10
    clock.value = Instant(clock.value.value + timedelta(seconds=10))
    assert limiter.consume("key", limit=1, window=timedelta(seconds=10), now=clock()) is None
    with pytest.raises(ValueError, match="positive"):
        limiter.consume("key", limit=0, window=timedelta(seconds=10), now=clock())
    bounded = InMemorySlidingWindowRateLimiter(max_keys=1)
    assert bounded.consume("first", limit=1, window=timedelta(seconds=10), now=clock()) is None
    assert bounded.consume("second", limit=1, window=timedelta(seconds=10), now=clock()) == 10
    with pytest.raises(ValueError, match="max_keys"):
        InMemorySlidingWindowRateLimiter(max_keys=0)
