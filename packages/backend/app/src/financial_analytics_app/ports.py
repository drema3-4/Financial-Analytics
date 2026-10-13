from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from financial_analytics_domain import (
    Account,
    AccountKind,
    Category,
    CategoryGroup,
    Currency,
    Instant,
    Money,
    Posting,
    Tag,
    Transaction,
    TransactionKind,
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


@dataclass(frozen=True, slots=True)
class TransactionCursor:
    occurred_at: datetime
    transaction_id: UUID
    snapshot_at: datetime


@dataclass(frozen=True, slots=True)
class TransactionQuery:
    account_id: UUID | None = None
    category_id: UUID | None = None
    tag_id: UUID | None = None
    kind: TransactionKind | None = None
    occurred_from: datetime | None = None
    occurred_to: datetime | None = None
    search: str | None = None


class LedgerRepository(Protocol):
    """A repository that is unavoidably scoped to exactly one owner."""

    @property
    def owner_id(self) -> UUID: ...

    def add_account(self, account: Account) -> None: ...

    def get_account(self, account_id: UUID) -> Account | None: ...

    def save_account(self, account: Account) -> Account: ...

    def list_accounts(self, *, include_archived: bool = False) -> tuple[Account, ...]: ...

    def get_or_create_system_account(
        self, kind: AccountKind, currency: Currency
    ) -> tuple[Account, bool]: ...

    def add_category_group(self, group: CategoryGroup) -> None: ...

    def get_category_group(self, group_id: UUID) -> CategoryGroup | None: ...

    def list_category_groups(self) -> tuple[CategoryGroup, ...]: ...

    def save_category_group(self, group: CategoryGroup) -> CategoryGroup: ...

    def add_category(self, category: Category) -> None: ...

    def get_category(self, category_id: UUID) -> Category | None: ...

    def list_categories(self) -> tuple[Category, ...]: ...

    def save_category(self, category: Category) -> Category: ...

    def add_tag(self, tag: Tag) -> None: ...

    def get_tag(self, tag_id: UUID) -> Tag | None: ...

    def list_tags(self) -> tuple[Tag, ...]: ...

    def add_transaction(
        self, transaction: Transaction, *, actor_id: UUID, request_id: UUID | None
    ) -> None: ...

    def get_transaction(self, transaction_id: UUID) -> Transaction | None: ...

    def list_transactions(
        self,
        query: TransactionQuery,
        *,
        cursor: TransactionCursor | None,
        limit: int,
    ) -> tuple[tuple[Transaction, ...], bool, datetime]: ...

    def list_postings(self, account_id: UUID | None = None) -> tuple[Posting, ...]: ...

    def rebuild_balances(self) -> dict[UUID, Money]: ...


class AuditRepository(Protocol):
    def append(self, event: AuditEvent) -> None: ...


class IdempotencyRepository(Protocol):
    def lock(self, scope: str, key: str) -> None: ...

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
