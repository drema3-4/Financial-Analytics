from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from financial_analytics_domain import (
    Account,
    Category,
    CategoryGroup,
    Instant,
    Money,
    Posting,
    Tag,
    Transaction,
)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: UUID
    owner_id: UUID
    actor_id: UUID
    event_type: str
    aggregate_type: str
    aggregate_id: UUID
    occurred_at: Instant
    request_id: UUID | None = None
    payload: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    owner_id: UUID
    scope: str
    key: str
    request_hash: str
    resource_type: str
    resource_id: UUID
    created_at: Instant


class LedgerRepository(Protocol):
    """A repository that is unavoidably scoped to exactly one owner."""

    @property
    def owner_id(self) -> UUID: ...

    def add_account(self, account: Account) -> None: ...

    def get_account(self, account_id: UUID) -> Account | None: ...

    def save_account(self, account: Account) -> Account: ...

    def add_category_group(self, group: CategoryGroup) -> None: ...

    def add_category(self, category: Category) -> None: ...

    def add_tag(self, tag: Tag) -> None: ...

    def add_transaction(
        self, transaction: Transaction, *, actor_id: UUID, request_id: UUID | None
    ) -> None: ...

    def get_transaction(self, transaction_id: UUID) -> Transaction | None: ...

    def list_postings(self, account_id: UUID | None = None) -> tuple[Posting, ...]: ...

    def rebuild_balances(self) -> dict[UUID, Money]: ...


class AuditRepository(Protocol):
    def append(self, event: AuditEvent) -> None: ...


class IdempotencyRepository(Protocol):
    def get(self, scope: str, key: str) -> IdempotencyRecord | None: ...

    def add(self, record: IdempotencyRecord) -> None: ...


class UnitOfWork(Protocol):
    ledger: LedgerRepository
    audit: AuditRepository
    idempotency: IdempotencyRepository

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class UnitOfWorkFactory(Protocol):
    def open(self, owner_id: UUID) -> UnitOfWork: ...
