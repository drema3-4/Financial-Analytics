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
from financial_analytics_domain import (
    EmailAddress,
    EmailToken,
    EmailTokenPurpose,
    Instant,
    Invitation,
    UserProfile,
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

    def add_allowlist_entry(self, entry: AllowlistEntry, *, request_id: UUID | None) -> None:
        self.allowlist[entry.email.value] = entry

    def is_email_allowed(self, email: EmailAddress) -> bool:
        entry = self.allowlist.get(email.value)
        return entry is not None and entry.revoked_at is None

    def create_invitation(
        self,
        invitation: Invitation,
        token: EmailToken,
        *,
        request_id: UUID | None,
    ) -> None:
        if not self.is_email_allowed(invitation.email):
            raise EmailNotAllowedError("not allowed")
        self.invitations[invitation.id] = invitation
        self.tokens[token.token_hash] = token

    def create_email_token(
        self, token: EmailToken, *, actor_id: UUID, request_id: UUID | None
    ) -> None:
        self.tokens[token.token_hash] = token

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
