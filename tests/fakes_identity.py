from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from financial_analytics_app.identity import (
    AllowlistEntry,
    AuthenticationRecord,
    BootstrapClosedError,
    EmailNotAllowedError,
    SessionRecord,
)
from financial_analytics_app.mail import EmailDeliveryJob
from financial_analytics_domain import (
    EmailAddress,
    EmailToken,
    EmailTokenPurpose,
    Instant,
    Invitation,
    UserProfile,
    UserStatus,
)


class FakePasswordHashes:
    def hash(self, password: str) -> str:
        return f"hashed::{password}"

    def verify(self, password_hash: str, password: str) -> bool:
        return password_hash == self.hash(password)

    def needs_rehash(self, password_hash: str) -> bool:
        return password_hash.startswith("old::")


class MutableClock:
    def __init__(self, value: datetime | None = None) -> None:
        self.value = Instant(value or datetime(2026, 10, 13, tzinfo=UTC))

    def __call__(self) -> Instant:
        return self.value


class FakeIdentityStore:
    def __init__(self) -> None:
        self.auth_by_email: dict[str, AuthenticationRecord] = {}
        self.profiles: dict[UUID, UserProfile] = {}
        self.sessions: dict[UUID, SessionRecord] = {}
        self.allowlist: dict[str, AllowlistEntry] = {}
        self.invitations: dict[UUID, Invitation] = {}
        self.tokens: dict[str, EmailToken] = {}
        self.email_jobs: list[EmailDeliveryJob] = []
        self.audit: list[tuple[str, dict[str, object]]] = []

    def create_master(
        self,
        *,
        profile: UserProfile,
        password_hash: str,
        request_id: UUID | None,
    ) -> None:
        if any(item.profile.is_master for item in self.auth_by_email.values()):
            raise BootstrapClosedError("closed")
        record = AuthenticationRecord(profile=profile, password_hash=password_hash)
        self.auth_by_email[profile.email.value] = record
        self.profiles[profile.id] = profile
        self.audit.append(("identity.master_created", {}))

    def get_authentication(self, email: EmailAddress) -> AuthenticationRecord | None:
        return self.auth_by_email.get(email.value)

    def get_profile(self, user_id: UUID) -> UserProfile | None:
        return self.profiles.get(user_id)

    def find_profile_by_email(self, email: EmailAddress) -> UserProfile | None:
        record = self.auth_by_email.get(email.value)
        return None if record is None else record.profile

    def replace_password_hash(self, user_id: UUID, password_hash: str, now: Instant) -> None:
        profile = self.profiles[user_id]
        self.auth_by_email[profile.email.value] = AuthenticationRecord(profile, password_hash)

    def create_session(
        self,
        session: SessionRecord,
        *,
        event_type: str,
        request_id: UUID | None,
    ) -> None:
        self.sessions[session.id] = session
        self.audit.append((event_type, {}))

    def get_session(self, session_id: UUID) -> SessionRecord | None:
        return self.sessions.get(session_id)

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
        current = self.sessions.get(session_id)
        if (
            current is None
            or current.revoked_at is not None
            or current.refresh_expires_at.value <= rotated_at.value
        ):
            return None
        if current.refresh_hash != expected_refresh_hash:
            self.sessions[session_id] = replace(current, revoked_at=rotated_at)
            return None
        rotated = replace(
            current,
            access_hash=access_hash,
            refresh_hash=refresh_hash,
            csrf_hash=csrf_hash,
            access_expires_at=access_expires_at,
            rotated_at=rotated_at,
        )
        self.sessions[session_id] = rotated
        return rotated

    def revoke_session(self, session_id: UUID, *, now: Instant, request_id: UUID | None) -> bool:
        current = self.sessions.get(session_id)
        if current is None or current.revoked_at is not None:
            return False
        self.sessions[session_id] = replace(current, revoked_at=now)
        return True

    def revoke_all_sessions(self, owner_id: UUID, *, now: Instant, request_id: UUID | None) -> int:
        changed = 0
        for session_id, current in tuple(self.sessions.items()):
            if current.owner_id == owner_id and current.revoked_at is None:
                self.sessions[session_id] = replace(current, revoked_at=now)
                changed += 1
        return changed

    def add_allowlist_entry(
        self, entry: AllowlistEntry, *, request_id: UUID | None
    ) -> AllowlistEntry:
        current = self.allowlist.get(entry.email.value)
        if current is not None and current.revoked_at is None:
            return current
        self.allowlist[entry.email.value] = entry
        return entry

    def list_allowlist_entries(self) -> tuple[AllowlistEntry, ...]:
        return tuple(self.allowlist.values())

    def revoke_allowlist_entry(
        self,
        entry_id: UUID,
        *,
        actor_id: UUID,
        now: Instant,
        request_id: UUID | None,
    ) -> AllowlistEntry | None:
        for email, entry in self.allowlist.items():
            if entry.id != entry_id:
                continue
            revoked = replace(entry, revoked_at=now)
            self.allowlist[email] = revoked
            record = self.auth_by_email.get(email)
            if record is not None and not record.profile.is_master:
                disabled = replace(record.profile, status=UserStatus.DISABLED)
                self.profiles[disabled.id] = disabled
                self.auth_by_email[email] = replace(record, profile=disabled)
            return revoked
        return None

    def is_email_allowed(self, email: EmailAddress) -> bool:
        entry = self.allowlist.get(email.value)
        return entry is not None and entry.revoked_at is None

    def create_invitation(
        self,
        invitation: Invitation,
        token: EmailToken,
        *,
        email_job: EmailDeliveryJob | None = None,
        request_id: UUID | None,
    ) -> None:
        if not self.is_email_allowed(invitation.email):
            raise EmailNotAllowedError("not allowed")
        self.invitations[invitation.id] = invitation
        self.tokens[token.token_hash] = token
        if email_job is not None:
            self.email_jobs.append(email_job)

    def list_invitations(self) -> tuple[Invitation, ...]:
        return tuple(self.invitations.values())

    def create_email_token(
        self,
        token: EmailToken,
        *,
        actor_id: UUID,
        email_job: EmailDeliveryJob | None = None,
        request_id: UUID | None,
    ) -> None:
        self.tokens[token.token_hash] = token
        if email_job is not None:
            self.email_jobs.append(email_job)

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
        token = self.tokens.get(token_hash)
        invitation = (
            None
            if token is None or token.invitation_id is None
            else self.invitations.get(token.invitation_id)
        )
        if (
            token is None
            or token.id != token_id
            or token.purpose is not EmailTokenPurpose.INVITATION
            or token.consumed_at is not None
            or token.revoked_at is not None
            or token.expires_at.value <= now.value
            or invitation is None
            or invitation.accepted_at is not None
            or invitation.revoked_at is not None
            or not self.is_email_allowed(invitation.email)
            or invitation.email.value in self.auth_by_email
        ):
            if token is not None:
                self.audit.append(("identity.email_token_replay_rejected", {}))
            return None
        accepted = replace(
            profile,
            email=invitation.email,
            is_admin=invitation.is_admin,
            email_verified_at=now,
        )
        self.tokens[token_hash] = replace(token, consumed_at=now)
        self.invitations[invitation.id] = replace(invitation, accepted_at=now)
        self.profiles[accepted.id] = accepted
        self.auth_by_email[accepted.email.value] = AuthenticationRecord(accepted, password_hash)
        return accepted

    def verify_email(
        self,
        token_id: UUID,
        token_hash: str,
        *,
        now: Instant,
        request_id: UUID | None,
    ) -> UserProfile | None:
        token = self._valid_user_token(token_id, token_hash, EmailTokenPurpose.VERIFY_EMAIL, now)
        if token is None or token.user_id is None:
            return None
        profile = replace(self.profiles[token.user_id], email_verified_at=now)
        self.profiles[profile.id] = profile
        record = self.auth_by_email[profile.email.value]
        self.auth_by_email[profile.email.value] = replace(record, profile=profile)
        self.tokens[token_hash] = replace(token, consumed_at=now)
        return profile

    def reset_password(
        self,
        token_id: UUID,
        token_hash: str,
        *,
        password_hash: str,
        now: Instant,
        request_id: UUID | None,
    ) -> UserProfile | None:
        token = self._valid_user_token(token_id, token_hash, EmailTokenPurpose.RESET_PASSWORD, now)
        if token is None or token.user_id is None:
            return None
        profile = self.profiles[token.user_id]
        self.auth_by_email[profile.email.value] = AuthenticationRecord(profile, password_hash)
        self.tokens[token_hash] = replace(token, consumed_at=now)
        for session_id, current in tuple(self.sessions.items()):
            if current.owner_id == profile.id and current.revoked_at is None:
                self.sessions[session_id] = replace(current, revoked_at=now)
        return profile

    def _valid_user_token(
        self,
        token_id: UUID,
        token_hash: str,
        purpose: EmailTokenPurpose,
        now: Instant,
    ) -> EmailToken | None:
        token = self.tokens.get(token_hash)
        if (
            token is None
            or token.id != token_id
            or token.purpose is not purpose
            or token.user_id is None
            or token.consumed_at is not None
            or token.revoked_at is not None
            or token.expires_at.value <= now.value
        ):
            if token is not None:
                self.audit.append(("identity.email_token_replay_rejected", {}))
            return None
        return token

    def consume_email_token(
        self,
        token_id: UUID,
        token_hash: str,
        purpose: EmailTokenPurpose,
        *,
        now: Instant,
        request_id: UUID | None,
    ) -> EmailToken | None:
        token = self.tokens.get(token_hash)
        if (
            token is None
            or token.id != token_id
            or token.purpose is not purpose
            or token.consumed_at is not None
            or token.revoked_at is not None
            or token.expires_at.value <= now.value
        ):
            return None
        consumed = replace(token, consumed_at=now)
        self.tokens[token_hash] = consumed
        return consumed
