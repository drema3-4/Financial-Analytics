from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from financial_analytics_domain.values import Currency, Instant

_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}$")
_LOCALE_RE = re.compile(r"^[a-z]{2,3}(?:-[A-Z]{2})?$")


@dataclass(frozen=True, slots=True)
class EmailAddress:
    """A normalized identity key; display casing is intentionally not retained."""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip().lower()
        if len(normalized) > 254 or _EMAIL_RE.fullmatch(normalized) is None:
            raise ValueError("email must be a valid address")
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class UserProfile:
    id: UUID
    email: EmailAddress
    base_currency: Currency
    locale: str
    timezone: str
    status: UserStatus
    is_master: bool
    created_at: Instant
    is_admin: bool = False
    email_verified_at: Instant | None = None

    def __post_init__(self) -> None:
        if _LOCALE_RE.fullmatch(self.locale) is None:
            raise ValueError("locale must look like ru or ru-RU")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError("timezone must be an IANA timezone") from error

    @property
    def enabled(self) -> bool:
        return self.status is UserStatus.ACTIVE

    @property
    def can_manage_access(self) -> bool:
        return self.is_master or self.is_admin


class EmailTokenPurpose(StrEnum):
    INVITATION = "invitation"
    VERIFY_EMAIL = "verify_email"
    RESET_PASSWORD = "reset_password"


@dataclass(frozen=True, slots=True)
class Invitation:
    id: UUID
    email: EmailAddress
    invited_by: UUID
    created_at: Instant
    expires_at: Instant
    is_admin: bool = False
    accepted_at: Instant | None = None
    revoked_at: Instant | None = None

    def __post_init__(self) -> None:
        if self.expires_at.value <= self.created_at.value:
            raise ValueError("invitation expiry must be after creation")


@dataclass(frozen=True, slots=True)
class EmailToken:
    id: UUID
    purpose: EmailTokenPurpose
    token_hash: str
    expires_at: Instant
    created_at: Instant
    user_id: UUID | None = None
    invitation_id: UUID | None = None
    consumed_at: Instant | None = None
    revoked_at: Instant | None = None

    def __post_init__(self) -> None:
        if len(self.token_hash) != 64:
            raise ValueError("token_hash must be a SHA-256-shaped digest")
        if (self.user_id is None) == (self.invitation_id is None):
            raise ValueError("email token must target exactly one user or invitation")
        if self.expires_at.value <= self.created_at.value:
            raise ValueError("email token expiry must be after creation")
