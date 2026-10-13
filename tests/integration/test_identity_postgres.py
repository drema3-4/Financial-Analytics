from __future__ import annotations

import json
from datetime import timedelta

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from financial_analytics_app.identity import (
    AuthService,
    BootstrapClosedError,
    DisabledUserError,
    EmailTokenInvalidError,
    InvalidSessionError,
    InvitationService,
)
from financial_analytics_domain import EmailTokenPurpose, Instant
from financial_analytics_infra.identity import PostgresIdentityStore
from financial_analytics_infra.models import (
    AuditEventModel,
    CredentialModel,
    EmailTokenModel,
    SessionModel,
    UserModel,
)
from financial_analytics_infra.security import (
    Argon2idPasswordHashes,
    HmacSecretProvider,
    InMemorySlidingWindowRateLimiter,
)
from tests.fakes_identity import MutableClock

pytestmark = pytest.mark.integration


def test_identity_security_matrix_and_secret_redaction(postgres_engine: Engine) -> None:
    store = PostgresIdentityStore("unused", engine=postgres_engine)
    clock = MutableClock()
    service = AuthService(
        store,
        Argon2idPasswordHashes(),
        HmacSecretProvider("session-secret-key-for-integration"),
        HmacSecretProvider("csrf-secret-key-for-integration-000"),
        InMemorySlidingWindowRateLimiter(),
        clock=clock,
    )
    password = "correct horse battery staple"
    original = service.bootstrap_master(
        email="master@example.com",
        password=password,
        base_currency="RUB",
        locale="ru-RU",
        timezone="Europe/Saratov",
    )
    with pytest.raises(BootstrapClosedError):
        service.bootstrap_master(
            email="other@example.com",
            password="another very strong password",
            base_currency="USD",
            locale="en-US",
            timezone="UTC",
        )

    with Session(postgres_engine) as db:
        credential = db.scalar(
            select(CredentialModel).where(CredentialModel.user_id == original.profile.id)
        )
        assert credential is not None
        assert credential.password_hash.startswith("$argon2id$")
        assert password not in credential.password_hash
        persisted = db.scalars(
            select(SessionModel).where(SessionModel.owner_id == original.profile.id)
        ).one()
        serialized_session = " ".join(
            [persisted.access_hash, persisted.refresh_hash, persisted.csrf_hash]
        )
        assert original.access_token not in serialized_session
        assert original.refresh_token not in serialized_session
        assert original.csrf_token not in serialized_session

    authenticated = service.authenticate_access(original.access_token)
    assert authenticated.profile.id == original.profile.id
    rotated = service.refresh(
        original.refresh_token,
        csrf_cookie=original.csrf_token,
        csrf_header=original.csrf_token,
        rate_limit_key="integration-client",
    )
    with pytest.raises(InvalidSessionError):
        service.refresh(
            original.refresh_token,
            csrf_cookie=rotated.csrf_token,
            csrf_header=rotated.csrf_token,
            rate_limit_key="integration-client",
        )
    with pytest.raises(InvalidSessionError):
        service.authenticate_access(rotated.access_token)

    active = service.login("master@example.com", password, rate_limit_key="integration-client-2")
    with Session(postgres_engine) as db, db.begin():
        db.execute(
            update(UserModel).where(UserModel.id == active.profile.id).values(status="disabled")
        )
    with pytest.raises(DisabledUserError):
        service.authenticate_access(active.access_token)
    with pytest.raises(DisabledUserError):
        service.login("master@example.com", password, rate_limit_key="disabled-client")

    with Session(postgres_engine) as db, db.begin():
        db.execute(
            update(UserModel).where(UserModel.id == active.profile.id).values(status="active")
        )
    active = service.login("master@example.com", password, rate_limit_key="logout-client")
    auth = service.authenticate_access(active.access_token)
    assert (
        service.logout_all(auth, csrf_cookie=active.csrf_token, csrf_header=active.csrf_token) >= 1
    )
    with pytest.raises(InvalidSessionError):
        service.authenticate_access(active.access_token)

    invitations = InvitationService(
        store,
        HmacSecretProvider("email-token-secret-for-integration"),
        clock=clock,
    )
    invitations.allow_email("guest@example.com", actor_id=active.profile.id)
    _, raw_email_token = invitations.issue_invitation(
        "guest@example.com", actor_id=active.profile.id
    )
    with Session(postgres_engine) as db:
        email_token = db.scalars(select(EmailTokenModel)).one()
        assert raw_email_token != email_token.token_hash
        assert raw_email_token.split(".", 1)[1] not in email_token.token_hash
    invitations.consume_invitation(raw_email_token)
    with pytest.raises(EmailTokenInvalidError):
        invitations.consume_invitation(raw_email_token)

    user_token, raw_user_token = invitations.issue_user_token(
        active.profile.id,
        EmailTokenPurpose.RESET_PASSWORD,
        actor_id=active.profile.id,
    )
    assert (
        invitations.consume_user_token(raw_user_token, EmailTokenPurpose.RESET_PASSWORD).id
        == user_token.id
    )
    with pytest.raises(EmailTokenInvalidError):
        invitations.consume_user_token(raw_user_token, EmailTokenPurpose.RESET_PASSWORD)

    _, expiring_token = invitations.issue_invitation(
        "guest@example.com", actor_id=active.profile.id
    )
    clock.value = Instant(clock.value.value + timedelta(hours=25))
    with pytest.raises(EmailTokenInvalidError):
        invitations.consume_invitation(expiring_token)

    with Session(postgres_engine) as db:
        audit_payloads = json.dumps(
            [row.payload for row in db.scalars(select(AuditEventModel))], sort_keys=True
        )
        assert password not in audit_payloads
        assert original.refresh_token not in audit_payloads
        assert raw_email_token not in audit_payloads
