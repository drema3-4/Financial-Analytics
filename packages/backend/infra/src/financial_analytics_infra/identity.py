from __future__ import annotations

import hmac
from uuid import UUID, uuid4

from sqlalchemy import Engine, create_engine, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from financial_analytics_app.identity import (
    AllowlistEntry,
    AuthenticationRecord,
    BootstrapClosedError,
    EmailNotAllowedError,
    SessionRecord,
)
from financial_analytics_app.mail import EmailDeliveryJob
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
from financial_analytics_infra.models import (
    AuditEventModel,
    CredentialModel,
    EmailAllowlistModel,
    EmailDeliveryJobModel,
    EmailTokenModel,
    InvitationModel,
    SessionModel,
    UserModel,
    UserProfileModel,
)

_BOOTSTRAP_ADVISORY_LOCK = 1_468_029_173


class PostgresIdentityStore:
    """Transactional PostgreSQL identity adapter with atomic token consumption."""

    def __init__(self, database_url: str, *, engine: Engine | None = None) -> None:
        self._owns_engine = engine is None
        self._engine = engine or create_engine(database_url, pool_pre_ping=True)
        self._sessions = sessionmaker(self._engine, expire_on_commit=False)

    def close(self) -> None:
        if self._owns_engine:
            self._engine.dispose()

    def create_master(
        self,
        *,
        profile: UserProfile,
        password_hash: str,
        request_id: UUID | None,
    ) -> None:
        try:
            with self._sessions.begin() as session:
                session.execute(select(func.pg_advisory_xact_lock(_BOOTSTRAP_ADVISORY_LOCK)))
                if session.scalar(select(UserModel.id).where(UserModel.is_master.is_(True))):
                    raise BootstrapClosedError("master bootstrap is already complete")
                session.add(
                    UserModel(
                        id=profile.id,
                        status=profile.status.value,
                        is_master=True,
                        is_admin=False,
                        email_verified_at=(
                            None
                            if profile.email_verified_at is None
                            else profile.email_verified_at.value
                        ),
                        created_at=profile.created_at.value,
                        updated_at=profile.created_at.value,
                    )
                )
                session.flush()
                session.add(
                    UserProfileModel(
                        user_id=profile.id,
                        base_currency=profile.base_currency.code,
                        locale=profile.locale,
                        timezone=profile.timezone,
                        created_at=profile.created_at.value,
                        updated_at=profile.created_at.value,
                    )
                )
                session.add(
                    CredentialModel(
                        user_id=profile.id,
                        email=profile.email.value,
                        password_hash=password_hash,
                        password_changed_at=profile.created_at.value,
                    )
                )
                session.flush()
                self._audit(
                    session,
                    owner_id=profile.id,
                    actor_id=profile.id,
                    event_type="identity.master_created",
                    aggregate_type="user",
                    aggregate_id=profile.id,
                    occurred_at=profile.created_at,
                    request_id=request_id,
                    payload={"is_master": True},
                )
        except IntegrityError as error:
            raise BootstrapClosedError("master bootstrap is already complete") from error

    def get_authentication(self, email: EmailAddress) -> AuthenticationRecord | None:
        with self._sessions() as session:
            row = session.execute(
                select(CredentialModel, UserModel, UserProfileModel)
                .join(UserModel, UserModel.id == CredentialModel.user_id)
                .join(UserProfileModel, UserProfileModel.user_id == UserModel.id)
                .where(CredentialModel.email == email.value)
            ).one_or_none()
            if row is None:
                return None
            credential, user, profile = row
            return AuthenticationRecord(
                profile=_profile_from_rows(user, credential, profile),
                password_hash=credential.password_hash,
            )

    def get_profile(self, user_id: UUID) -> UserProfile | None:
        with self._sessions() as session:
            row = session.execute(
                select(UserModel, CredentialModel, UserProfileModel)
                .join(CredentialModel, CredentialModel.user_id == UserModel.id)
                .join(UserProfileModel, UserProfileModel.user_id == UserModel.id)
                .where(UserModel.id == user_id)
            ).one_or_none()
            if row is None:
                return None
            user, credential, profile = row
            return _profile_from_rows(user, credential, profile)

    def find_profile_by_email(self, email: EmailAddress) -> UserProfile | None:
        authentication = self.get_authentication(email)
        return None if authentication is None else authentication.profile

    def replace_password_hash(self, user_id: UUID, password_hash: str, now: Instant) -> None:
        with self._sessions.begin() as session:
            changed = session.scalar(
                update(CredentialModel)
                .where(CredentialModel.user_id == user_id)
                .values(password_hash=password_hash, password_changed_at=now.value)
                .returning(CredentialModel.user_id)
            )
            if changed is not None:
                self._audit(
                    session,
                    owner_id=user_id,
                    actor_id=user_id,
                    event_type="identity.password_rehashed",
                    aggregate_type="credential",
                    aggregate_id=user_id,
                    occurred_at=now,
                    request_id=None,
                )

    def create_session(
        self,
        session_record: SessionRecord,
        *,
        event_type: str,
        request_id: UUID | None,
    ) -> None:
        with self._sessions.begin() as session:
            session.add(_session_to_row(session_record))
            self._audit(
                session,
                owner_id=session_record.owner_id,
                actor_id=session_record.owner_id,
                event_type=event_type,
                aggregate_type="session",
                aggregate_id=session_record.id,
                occurred_at=session_record.created_at,
                request_id=request_id,
            )

    def get_session(self, session_id: UUID) -> SessionRecord | None:
        with self._sessions() as session:
            row = session.get(SessionModel, session_id)
            return None if row is None else _session_from_row(row)

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
    ) -> SessionRecord | None:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(SessionModel).where(SessionModel.id == session_id).with_for_update()
            )
            if (
                row is None
                or row.revoked_at is not None
                or row.refresh_expires_at <= rotated_at.value
            ):
                return None
            if not hmac.compare_digest(row.refresh_hash, expected_refresh_hash):
                row.revoked_at = rotated_at.value
                self._audit(
                    session,
                    owner_id=row.owner_id,
                    actor_id=row.owner_id,
                    event_type="identity.refresh_replay_rejected",
                    aggregate_type="session",
                    aggregate_id=row.id,
                    occurred_at=rotated_at,
                    request_id=request_id,
                )
                return None
            row.access_hash = access_hash
            row.refresh_hash = refresh_hash
            row.csrf_hash = csrf_hash
            row.access_expires_at = access_expires_at.value
            row.rotated_at = rotated_at.value
            self._audit(
                session,
                owner_id=row.owner_id,
                actor_id=row.owner_id,
                event_type="identity.session_refreshed",
                aggregate_type="session",
                aggregate_id=row.id,
                occurred_at=rotated_at,
                request_id=request_id,
            )
            session.flush()
            return _session_from_row(row)

    def revoke_session(self, session_id: UUID, *, now: Instant, request_id: UUID | None) -> bool:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(SessionModel).where(SessionModel.id == session_id).with_for_update()
            )
            if row is None or row.revoked_at is not None:
                return False
            row.revoked_at = now.value
            self._audit(
                session,
                owner_id=row.owner_id,
                actor_id=row.owner_id,
                event_type="identity.session_revoked",
                aggregate_type="session",
                aggregate_id=row.id,
                occurred_at=now,
                request_id=request_id,
            )
            return True

    def revoke_all_sessions(self, owner_id: UUID, *, now: Instant, request_id: UUID | None) -> int:
        with self._sessions.begin() as session:
            active_ids = tuple(
                session.scalars(
                    select(SessionModel.id)
                    .where(SessionModel.owner_id == owner_id, SessionModel.revoked_at.is_(None))
                    .with_for_update()
                )
            )
            if active_ids:
                session.execute(
                    update(SessionModel)
                    .where(SessionModel.id.in_(active_ids))
                    .values(revoked_at=now.value)
                )
            changed = len(active_ids)
            self._audit(
                session,
                owner_id=owner_id,
                actor_id=owner_id,
                event_type="identity.all_sessions_revoked",
                aggregate_type="user",
                aggregate_id=owner_id,
                occurred_at=now,
                request_id=request_id,
                payload={"revoked_count": changed},
            )
            return changed

    def add_allowlist_entry(
        self, entry: AllowlistEntry, *, request_id: UUID | None
    ) -> AllowlistEntry:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(EmailAllowlistModel)
                .where(EmailAllowlistModel.email == entry.email.value)
                .with_for_update()
            )
            if row is None:
                row = EmailAllowlistModel(
                    id=entry.id,
                    email=entry.email.value,
                    added_by=entry.added_by,
                    created_at=entry.created_at.value,
                    revoked_at=None,
                )
                session.add(row)
                event_type = "identity.allowlist_added"
            elif row.revoked_at is None:
                return _allowlist_from_row(row)
            else:
                row.added_by = entry.added_by
                row.created_at = entry.created_at.value
                row.revoked_at = None
                credential = session.scalar(
                    select(CredentialModel).where(CredentialModel.email == entry.email.value)
                )
                if credential is not None:
                    user = session.get(UserModel, credential.user_id)
                    if user is not None and not user.is_master:
                        user.status = UserStatus.ACTIVE.value
                        user.updated_at = entry.created_at.value
                event_type = "identity.allowlist_reactivated"
            self._audit(
                session,
                owner_id=entry.added_by,
                actor_id=entry.added_by,
                event_type=event_type,
                aggregate_type="allowlist_entry",
                aggregate_id=row.id,
                occurred_at=entry.created_at,
                request_id=request_id,
            )
            session.flush()
            return _allowlist_from_row(row)

    def list_allowlist_entries(self) -> tuple[AllowlistEntry, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(EmailAllowlistModel).order_by(
                    EmailAllowlistModel.created_at.desc(), EmailAllowlistModel.id
                )
            ).all()
            return tuple(_allowlist_from_row(row) for row in rows)

    def revoke_allowlist_entry(
        self,
        entry_id: UUID,
        *,
        actor_id: UUID,
        now: Instant,
        request_id: UUID | None,
    ) -> AllowlistEntry | None:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(EmailAllowlistModel)
                .where(EmailAllowlistModel.id == entry_id)
                .with_for_update()
            )
            if row is None:
                return None
            if row.revoked_at is None:
                row.revoked_at = now.value
                credential = session.scalar(
                    select(CredentialModel).where(CredentialModel.email == row.email)
                )
                owner_id = actor_id
                if credential is not None:
                    user = session.get(UserModel, credential.user_id)
                    if user is not None and not user.is_master:
                        user.status = UserStatus.DISABLED.value
                        user.updated_at = now.value
                        owner_id = user.id
                        session.execute(
                            update(SessionModel)
                            .where(
                                SessionModel.owner_id == user.id,
                                SessionModel.revoked_at.is_(None),
                            )
                            .values(revoked_at=now.value)
                        )
                        session.execute(
                            update(EmailTokenModel)
                            .where(
                                EmailTokenModel.user_id == user.id,
                                EmailTokenModel.consumed_at.is_(None),
                                EmailTokenModel.revoked_at.is_(None),
                            )
                            .values(revoked_at=now.value)
                        )
                invitation_ids = select(InvitationModel.id).where(
                    InvitationModel.email == row.email,
                    InvitationModel.accepted_at.is_(None),
                    InvitationModel.revoked_at.is_(None),
                )
                token_ids = select(EmailTokenModel.id).where(
                    EmailTokenModel.invitation_id.in_(invitation_ids),
                    EmailTokenModel.consumed_at.is_(None),
                )
                session.execute(
                    update(EmailDeliveryJobModel)
                    .where(
                        EmailDeliveryJobModel.token_id.in_(token_ids),
                        EmailDeliveryJobModel.state.in_(("pending", "leased")),
                    )
                    .values(
                        state="dead_letter",
                        text_body=None,
                        lease_owner=None,
                        leased_until=None,
                        last_error="AccessRevoked",
                    )
                )
                session.execute(
                    update(EmailTokenModel)
                    .where(
                        EmailTokenModel.invitation_id.in_(invitation_ids),
                        EmailTokenModel.consumed_at.is_(None),
                        EmailTokenModel.revoked_at.is_(None),
                    )
                    .values(revoked_at=now.value)
                )
                session.execute(
                    update(InvitationModel)
                    .where(
                        InvitationModel.email == row.email,
                        InvitationModel.accepted_at.is_(None),
                        InvitationModel.revoked_at.is_(None),
                    )
                    .values(revoked_at=now.value)
                )
                self._audit(
                    session,
                    owner_id=owner_id,
                    actor_id=actor_id,
                    event_type="identity.allowlist_revoked",
                    aggregate_type="allowlist_entry",
                    aggregate_id=row.id,
                    occurred_at=now,
                    request_id=request_id,
                    payload={"financial_data_preserved": True},
                )
            session.flush()
            return _allowlist_from_row(row)

    def is_email_allowed(self, email: EmailAddress) -> bool:
        with self._sessions() as session:
            return (
                session.scalar(
                    select(EmailAllowlistModel.id).where(
                        EmailAllowlistModel.email == email.value,
                        EmailAllowlistModel.revoked_at.is_(None),
                    )
                )
                is not None
            )

    def create_invitation(
        self,
        invitation: Invitation,
        token: EmailToken,
        *,
        email_job: EmailDeliveryJob | None = None,
        request_id: UUID | None,
    ) -> None:
        with self._sessions.begin() as session:
            allowed = session.scalar(
                select(EmailAllowlistModel.id).where(
                    EmailAllowlistModel.email == invitation.email.value,
                    EmailAllowlistModel.revoked_at.is_(None),
                )
            )
            if allowed is None:
                raise EmailNotAllowedError("email is not on the allowlist")
            session.add(
                InvitationModel(
                    id=invitation.id,
                    email=invitation.email.value,
                    invited_by=invitation.invited_by,
                    created_at=invitation.created_at.value,
                    expires_at=invitation.expires_at.value,
                    is_admin=invitation.is_admin,
                )
            )
            session.flush()
            session.add(_email_token_to_row(token))
            session.flush()
            if email_job is not None:
                session.add(_email_job_to_row(email_job))
            self._audit(
                session,
                owner_id=invitation.invited_by,
                actor_id=invitation.invited_by,
                event_type="identity.invitation_created",
                aggregate_type="invitation",
                aggregate_id=invitation.id,
                occurred_at=invitation.created_at,
                request_id=request_id,
                payload={"is_admin": invitation.is_admin},
            )

    def list_invitations(self) -> tuple[Invitation, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(InvitationModel).order_by(
                    InvitationModel.created_at.desc(), InvitationModel.id
                )
            ).all()
            return tuple(_invitation_from_row(row) for row in rows)

    def create_email_token(
        self,
        token: EmailToken,
        *,
        actor_id: UUID,
        email_job: EmailDeliveryJob | None = None,
        request_id: UUID | None,
    ) -> None:
        with self._sessions.begin() as session:
            session.add(_email_token_to_row(token))
            session.flush()
            if email_job is not None:
                session.add(_email_job_to_row(email_job))
            self._audit(
                session,
                owner_id=actor_id,
                actor_id=actor_id,
                event_type="identity.email_token_created",
                aggregate_type="email_token",
                aggregate_id=token.id,
                occurred_at=token.created_at,
                request_id=request_id,
                payload={"purpose": token.purpose.value},
            )

    def accept_invitation(
        self,
        token_id: UUID,
        token_hash: str,
        *,
        profile: UserProfile,
        password_hash: str,
        now: Instant,
        request_id: UUID | None,
    ) -> UserProfile | None:
        with self._sessions.begin() as session:
            token = session.scalar(
                select(EmailTokenModel).where(EmailTokenModel.id == token_id).with_for_update()
            )
            if token is None:
                return None
            invitation = (
                None
                if token.invitation_id is None
                else session.scalar(
                    select(InvitationModel)
                    .where(InvitationModel.id == token.invitation_id)
                    .with_for_update()
                )
            )
            allowed = (
                invitation is not None
                and session.scalar(
                    select(EmailAllowlistModel.id)
                    .where(
                        EmailAllowlistModel.email == invitation.email,
                        EmailAllowlistModel.revoked_at.is_(None),
                    )
                    .with_for_update()
                )
                is not None
            )
            duplicate = (
                invitation is not None
                and session.scalar(
                    select(CredentialModel.user_id).where(CredentialModel.email == invitation.email)
                )
                is not None
            )
            if (
                token.purpose != EmailTokenPurpose.INVITATION.value
                or not hmac.compare_digest(token.token_hash, token_hash)
                or token.consumed_at is not None
                or token.revoked_at is not None
                or token.expires_at <= now.value
                or invitation is None
                or invitation.revoked_at is not None
                or invitation.accepted_at is not None
                or invitation.expires_at <= now.value
                or not allowed
                or duplicate
            ):
                self._audit_token_rejection(session, token, now, request_id)
                return None
            accepted = UserProfile(
                id=profile.id,
                email=EmailAddress(invitation.email),
                base_currency=profile.base_currency,
                locale=profile.locale,
                timezone=profile.timezone,
                status=UserStatus.ACTIVE,
                is_master=False,
                created_at=now,
                is_admin=invitation.is_admin,
                email_verified_at=now,
            )
            user = UserModel(
                id=accepted.id,
                status=accepted.status.value,
                is_master=False,
                is_admin=accepted.is_admin,
                email_verified_at=now.value,
                created_at=now.value,
                updated_at=now.value,
            )
            session.add(user)
            session.flush()
            profile_row = UserProfileModel(
                user_id=accepted.id,
                base_currency=accepted.base_currency.code,
                locale=accepted.locale,
                timezone=accepted.timezone,
                created_at=now.value,
                updated_at=now.value,
            )
            credential = CredentialModel(
                user_id=accepted.id,
                email=accepted.email.value,
                password_hash=password_hash,
                password_changed_at=now.value,
            )
            session.add_all((profile_row, credential))
            token.consumed_at = now.value
            self._discard_email_job(session, token.id, now)
            invitation.accepted_at = now.value
            self._audit(
                session,
                owner_id=accepted.id,
                actor_id=accepted.id,
                event_type="identity.invitation_accepted",
                aggregate_type="user",
                aggregate_id=accepted.id,
                occurred_at=now,
                request_id=request_id,
                payload={"is_admin": accepted.is_admin},
            )
            return accepted

    def verify_email(
        self,
        token_id: UUID,
        token_hash: str,
        *,
        now: Instant,
        request_id: UUID | None,
    ) -> UserProfile | None:
        with self._sessions.begin() as session:
            token = self._lock_user_token(
                session,
                token_id,
                token_hash,
                EmailTokenPurpose.VERIFY_EMAIL,
                now,
                request_id,
            )
            if token is None or token.user_id is None:
                return None
            rows = self._profile_rows(session, token.user_id)
            if rows is None:
                return None
            user, credential, profile_row = rows
            token.consumed_at = now.value
            self._discard_email_job(session, token.id, now)
            user.email_verified_at = now.value
            user.updated_at = now.value
            self._audit(
                session,
                owner_id=user.id,
                actor_id=user.id,
                event_type="identity.email_verified",
                aggregate_type="user",
                aggregate_id=user.id,
                occurred_at=now,
                request_id=request_id,
            )
            session.flush()
            return _profile_from_rows(user, credential, profile_row)

    def reset_password(
        self,
        token_id: UUID,
        token_hash: str,
        *,
        password_hash: str,
        now: Instant,
        request_id: UUID | None,
    ) -> UserProfile | None:
        with self._sessions.begin() as session:
            token = self._lock_user_token(
                session,
                token_id,
                token_hash,
                EmailTokenPurpose.RESET_PASSWORD,
                now,
                request_id,
            )
            if token is None or token.user_id is None:
                return None
            rows = self._profile_rows(session, token.user_id)
            if rows is None:
                return None
            user, credential, profile_row = rows
            token.consumed_at = now.value
            self._discard_email_job(session, token.id, now)
            credential.password_hash = password_hash
            credential.password_changed_at = now.value
            session.execute(
                update(SessionModel)
                .where(
                    SessionModel.owner_id == user.id,
                    SessionModel.revoked_at.is_(None),
                )
                .values(revoked_at=now.value)
            )
            self._audit(
                session,
                owner_id=user.id,
                actor_id=user.id,
                event_type="identity.password_reset",
                aggregate_type="credential",
                aggregate_id=user.id,
                occurred_at=now,
                request_id=request_id,
            )
            session.flush()
            return _profile_from_rows(user, credential, profile_row)

    def consume_email_token(
        self,
        token_id: UUID,
        token_hash: str,
        purpose: EmailTokenPurpose,
        *,
        now: Instant,
        request_id: UUID | None,
    ) -> EmailToken | None:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(EmailTokenModel).where(EmailTokenModel.id == token_id).with_for_update()
            )
            if (
                row is None
                or row.purpose != purpose.value
                or not hmac.compare_digest(row.token_hash, token_hash)
                or row.consumed_at is not None
                or row.revoked_at is not None
                or row.expires_at <= now.value
            ):
                if row is not None:
                    self._audit_token_rejection(session, row, now, request_id)
                return None
            actor_id = row.user_id
            if row.invitation_id is not None:
                invitation = session.scalar(
                    select(InvitationModel)
                    .where(InvitationModel.id == row.invitation_id)
                    .with_for_update()
                )
                if (
                    invitation is None
                    or invitation.revoked_at is not None
                    or invitation.accepted_at is not None
                    or invitation.expires_at <= now.value
                    or session.scalar(
                        select(EmailAllowlistModel.id).where(
                            EmailAllowlistModel.email == invitation.email,
                            EmailAllowlistModel.revoked_at.is_(None),
                        )
                    )
                    is None
                ):
                    self._audit_token_rejection(session, row, now, request_id)
                    return None
                invitation.accepted_at = now.value
                actor_id = invitation.invited_by
            if actor_id is None:
                return None
            row.consumed_at = now.value
            self._discard_email_job(session, row.id, now)
            self._audit(
                session,
                owner_id=actor_id,
                actor_id=actor_id,
                event_type="identity.email_token_consumed",
                aggregate_type="email_token",
                aggregate_id=row.id,
                occurred_at=now,
                request_id=request_id,
                payload={"purpose": row.purpose},
            )
            session.flush()
            return _email_token_from_row(row)

    def _lock_user_token(
        self,
        session: Session,
        token_id: UUID,
        token_hash: str,
        purpose: EmailTokenPurpose,
        now: Instant,
        request_id: UUID | None,
    ) -> EmailTokenModel | None:
        row = session.scalar(
            select(EmailTokenModel).where(EmailTokenModel.id == token_id).with_for_update()
        )
        if (
            row is None
            or row.purpose != purpose.value
            or not hmac.compare_digest(row.token_hash, token_hash)
            or row.user_id is None
            or row.consumed_at is not None
            or row.revoked_at is not None
            or row.expires_at <= now.value
        ):
            if row is not None:
                self._audit_token_rejection(session, row, now, request_id)
            return None
        return row

    def _audit_token_rejection(
        self,
        session: Session,
        row: EmailTokenModel,
        now: Instant,
        request_id: UUID | None,
    ) -> None:
        owner_id = row.user_id
        if owner_id is None and row.invitation_id is not None:
            owner_id = session.scalar(
                select(InvitationModel.invited_by).where(InvitationModel.id == row.invitation_id)
            )
        if owner_id is None:
            return
        self._audit(
            session,
            owner_id=owner_id,
            actor_id=owner_id,
            event_type="identity.email_token_replay_rejected",
            aggregate_type="email_token",
            aggregate_id=row.id,
            occurred_at=now,
            request_id=request_id,
            payload={"purpose": row.purpose},
        )

    @staticmethod
    def _discard_email_job(session: Session, token_id: UUID, now: Instant) -> None:
        session.execute(
            update(EmailDeliveryJobModel)
            .where(
                EmailDeliveryJobModel.token_id == token_id,
                EmailDeliveryJobModel.state.in_(("pending", "leased")),
            )
            .values(
                state="completed",
                text_body=None,
                lease_owner=None,
                leased_until=None,
                last_error="TokenAlreadyConsumed",
                completed_at=now.value,
            )
        )

    @staticmethod
    def _profile_rows(
        session: Session, user_id: UUID
    ) -> tuple[UserModel, CredentialModel, UserProfileModel] | None:
        row = session.execute(
            select(UserModel, CredentialModel, UserProfileModel)
            .join(CredentialModel, CredentialModel.user_id == UserModel.id)
            .join(UserProfileModel, UserProfileModel.user_id == UserModel.id)
            .where(UserModel.id == user_id)
        ).one_or_none()
        if row is None:
            return None
        return row

    @staticmethod
    def _audit(
        session: Session,
        *,
        owner_id: UUID,
        actor_id: UUID,
        event_type: str,
        aggregate_type: str,
        aggregate_id: UUID,
        occurred_at: Instant,
        request_id: UUID | None,
        payload: dict[str, object] | None = None,
    ) -> None:
        session.add(
            AuditEventModel(
                id=uuid4(),
                owner_id=owner_id,
                actor_id=actor_id,
                event_type=event_type,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                occurred_at=occurred_at.value,
                request_id=request_id,
                payload=payload or {},
            )
        )


def _profile_from_rows(
    user: UserModel, credential: CredentialModel, profile: UserProfileModel
) -> UserProfile:
    return UserProfile(
        id=user.id,
        email=EmailAddress(credential.email),
        base_currency=Currency(profile.base_currency),
        locale=profile.locale,
        timezone=profile.timezone,
        status=UserStatus(user.status),
        is_master=user.is_master,
        created_at=Instant(user.created_at),
        is_admin=user.is_admin,
        email_verified_at=(
            None if user.email_verified_at is None else Instant(user.email_verified_at)
        ),
    )


def _allowlist_from_row(row: EmailAllowlistModel) -> AllowlistEntry:
    return AllowlistEntry(
        id=row.id,
        email=EmailAddress(row.email),
        added_by=row.added_by,
        created_at=Instant(row.created_at),
        revoked_at=None if row.revoked_at is None else Instant(row.revoked_at),
    )


def _invitation_from_row(row: InvitationModel) -> Invitation:
    return Invitation(
        id=row.id,
        email=EmailAddress(row.email),
        invited_by=row.invited_by,
        created_at=Instant(row.created_at),
        expires_at=Instant(row.expires_at),
        is_admin=row.is_admin,
        accepted_at=None if row.accepted_at is None else Instant(row.accepted_at),
        revoked_at=None if row.revoked_at is None else Instant(row.revoked_at),
    )


def _session_to_row(record: SessionRecord) -> SessionModel:
    return SessionModel(
        id=record.id,
        owner_id=record.owner_id,
        access_hash=record.access_hash,
        refresh_hash=record.refresh_hash,
        csrf_hash=record.csrf_hash,
        access_expires_at=record.access_expires_at.value,
        refresh_expires_at=record.refresh_expires_at.value,
        created_at=record.created_at.value,
        rotated_at=record.rotated_at.value,
        revoked_at=None if record.revoked_at is None else record.revoked_at.value,
    )


def _session_from_row(row: SessionModel) -> SessionRecord:
    return SessionRecord(
        id=row.id,
        owner_id=row.owner_id,
        access_hash=row.access_hash,
        refresh_hash=row.refresh_hash,
        csrf_hash=row.csrf_hash,
        access_expires_at=Instant(row.access_expires_at),
        refresh_expires_at=Instant(row.refresh_expires_at),
        created_at=Instant(row.created_at),
        rotated_at=Instant(row.rotated_at),
        revoked_at=None if row.revoked_at is None else Instant(row.revoked_at),
    )


def _email_token_to_row(token: EmailToken) -> EmailTokenModel:
    return EmailTokenModel(
        id=token.id,
        purpose=token.purpose.value,
        token_hash=token.token_hash,
        user_id=token.user_id,
        invitation_id=token.invitation_id,
        created_at=token.created_at.value,
        expires_at=token.expires_at.value,
        consumed_at=None if token.consumed_at is None else token.consumed_at.value,
        revoked_at=None if token.revoked_at is None else token.revoked_at.value,
    )


def _email_token_from_row(row: EmailTokenModel) -> EmailToken:
    return EmailToken(
        id=row.id,
        purpose=EmailTokenPurpose(row.purpose),
        token_hash=row.token_hash,
        user_id=row.user_id,
        invitation_id=row.invitation_id,
        created_at=Instant(row.created_at),
        expires_at=Instant(row.expires_at),
        consumed_at=None if row.consumed_at is None else Instant(row.consumed_at),
        revoked_at=None if row.revoked_at is None else Instant(row.revoked_at),
    )


def _email_job_to_row(job: EmailDeliveryJob) -> EmailDeliveryJobModel:
    return EmailDeliveryJobModel(
        id=job.id,
        token_id=job.token_id,
        purpose=job.purpose.value,
        recipient=job.recipient,
        subject=job.subject,
        text_body=job.text_body,
        state=job.state.value,
        attempts=job.attempts,
        available_at=job.available_at.value,
        created_at=job.created_at.value,
    )
