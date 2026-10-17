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
from financial_analytics_infra.mail import PostgresEmailJobRepository
from financial_analytics_infra.models import (
    AccountModel,
    AuditEventModel,
    CredentialModel,
    EmailDeliveryJobModel,
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
        Argon2idPasswordHashes(),
        public_base_url="https://finance.example.test",
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

    allowlist_entry = invitations.allow_email("member@example.com", actor_id=active.profile.id)
    _, registration_token = invitations.issue_invitation(
        "member@example.com", actor_id=active.profile.id
    )
    mail_repository = PostgresEmailJobRepository(postgres_engine)
    claimed = mail_repository.claim_jobs(
        clock(), worker_id="identity-test", lease_duration=timedelta(seconds=30), limit=20
    )
    member_job = next(job for job in claimed if job.recipient == "member@example.com")
    assert mail_repository.complete_job(
        member_job.id, worker_id="identity-test", completed_at=clock()
    )
    member = invitations.accept_invitation(
        registration_token,
        password="member correct horse battery",
        base_currency="RUB",
        locale="ru-RU",
        timezone="Europe/Saratov",
    )
    _, verification_token = invitations.issue_user_token(
        member.id, EmailTokenPurpose.VERIFY_EMAIL, actor_id=member.id
    )
    assert invitations.verify_email(verification_token).email_verified_at == clock()
    with pytest.raises(EmailTokenInvalidError):
        invitations.verify_email(verification_token)
    _, reset_token = invitations.issue_user_token(
        member.id, EmailTokenPurpose.RESET_PASSWORD, actor_id=member.id
    )
    member_session = service.login(
        "member@example.com", "member correct horse battery", rate_limit_key="member-login"
    )
    invitations.reset_password(reset_token, new_password="new member correct horse battery")
    with pytest.raises(InvalidSessionError):
        service.authenticate_access(member_session.access_token)
    with pytest.raises(EmailTokenInvalidError):
        invitations.reset_password(reset_token, new_password="new member correct horse battery")
    assert (
        service.login(
            "member@example.com", "new member correct horse battery", rate_limit_key="member-reset"
        ).profile.id
        == member.id
    )
    with pytest.raises(EmailTokenInvalidError):
        invitations.accept_invitation(
            registration_token,
            password="member correct horse battery",
            base_currency="RUB",
            locale="ru-RU",
            timezone="Europe/Saratov",
        )
    with Session(postgres_engine) as db, db.begin():
        account = AccountModel(
            id=member.id.__class__(int=999),
            owner_id=member.id,
            name="Preserved account",
            kind="bank",
            currency="RUB",
            created_at=clock().value,
            updated_at=clock().value,
        )
        db.add(account)
        account_id = account.id
    revoked = invitations.revoke_allowlist(
        allowlist_entry.id,
        actor_id=active.profile.id,
    )
    assert revoked is not None and revoked.revoked_at is not None
    with Session(postgres_engine) as db:
        persisted_member = db.get(UserModel, member.id)
        assert persisted_member is not None and persisted_member.status == "disabled"
        assert db.get(AccountModel, account_id) is not None
        delivered = db.get(EmailDeliveryJobModel, member_job.id)
        assert delivered is not None and delivered.text_body is None

    with Session(postgres_engine) as db:
        audit_payloads = json.dumps(
            [row.payload for row in db.scalars(select(AuditEventModel))], sort_keys=True
        )
        assert password not in audit_payloads
        assert original.refresh_token not in audit_payloads
        assert raw_email_token not in audit_payloads
        event_types = set(db.scalars(select(AuditEventModel.event_type)))
        assert "identity.email_token_replay_rejected" in event_types
        assert "identity.allowlist_revoked" in event_types

    invitations.allow_email("delivery-failure@example.com", actor_id=active.profile.id)
    invitations.issue_invitation("delivery-failure@example.com", actor_id=active.profile.id)
    for attempt in range(5):
        jobs = mail_repository.claim_jobs(
            clock(), worker_id="mail-failure", lease_duration=timedelta(seconds=30), limit=20
        )
        failed_job = next(job for job in jobs if job.recipient == "delivery-failure@example.com")
        assert failed_job.attempts == attempt + 1
        assert not mail_repository.complete_job(
            failed_job.id, worker_id="wrong-owner", completed_at=clock()
        )
        assert mail_repository.fail_job(
            failed_job.id,
            worker_id="mail-failure",
            failed_at=clock(),
            error_code="TimeoutError",
            base_backoff=timedelta(seconds=1),
        )
        clock.value = Instant(clock().value + timedelta(seconds=60))
    with Session(postgres_engine) as db:
        dead_job = db.get(EmailDeliveryJobModel, failed_job.id)
        assert dead_job is not None and dead_job.state == "dead_letter"
        assert dead_job.text_body is None

    invitations.allow_email("lease-expired@example.com", actor_id=active.profile.id)
    invitations.issue_invitation("lease-expired@example.com", actor_id=active.profile.id)
    for _ in range(5):
        mail_repository.claim_jobs(
            clock(), worker_id="crashed-mail", lease_duration=timedelta(seconds=30), limit=20
        )
        clock.value = Instant(clock().value + timedelta(seconds=31))
    assert not mail_repository.claim_jobs(
        clock(), worker_id="recovered-mail", lease_duration=timedelta(seconds=30), limit=20
    )
    with Session(postgres_engine) as db:
        expired_job = db.scalar(
            select(EmailDeliveryJobModel).where(
                EmailDeliveryJobModel.recipient == "lease-expired@example.com"
            )
        )
        assert expired_job is not None and expired_job.state == "dead_letter"
        assert expired_job.text_body is None and expired_job.lease_owner is None
