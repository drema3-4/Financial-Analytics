from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from financial_analytics_domain import (
    Account,
    AccountKind,
    Category,
    CategoryGroup,
    Currency,
    DepositTerms,
    FinancialGoal,
    ForecastScenario,
    Instant,
    Money,
    OutboxJob,
    Posting,
    RecurringOperation,
    RecurringRule,
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

    def list_deposit_transactions(self, deposit_id: UUID) -> tuple[Transaction, ...]: ...

    def list_analytics_transactions(self, occurred_to: datetime) -> tuple[Transaction, ...]: ...

    def rebuild_balances(self) -> dict[UUID, Money]: ...


class AuditRepository(Protocol):
    def append(self, event: AuditEvent) -> None: ...


class IdempotencyRepository(Protocol):
    def lock(self, scope: str, key: str) -> None: ...

    def get(self, scope: str, key: str) -> IdempotencyRecord | None: ...

    def add(self, record: IdempotencyRecord) -> None: ...


class DepositRepository(Protocol):
    def add(self, terms: DepositTerms) -> None: ...

    def get(self, deposit_id: UUID) -> DepositTerms | None: ...

    def list(self, *, include_archived: bool = False) -> tuple[DepositTerms, ...]: ...

    def save(self, terms: DepositTerms, *, expected_version: int) -> DepositTerms: ...

    def find_by_principal_account(self, account_id: UUID) -> DepositTerms | None: ...


class ForecastRepository(Protocol):
    def add_scenario(self, scenario: ForecastScenario) -> None: ...

    def get_scenario(self, scenario_id: UUID) -> ForecastScenario | None: ...

    def list_scenarios(self) -> tuple[ForecastScenario, ...]: ...

    def save_scenario(
        self, scenario: ForecastScenario, *, expected_version: int
    ) -> ForecastScenario: ...

    def add_goal(self, goal: FinancialGoal) -> None: ...

    def get_goal(self, goal_id: UUID) -> FinancialGoal | None: ...

    def list_goals(self) -> tuple[FinancialGoal, ...]: ...

    def save_goal(self, goal: FinancialGoal, *, expected_version: int) -> FinancialGoal: ...

    def list_recurring_rules(self) -> tuple[RecurringRule, ...]: ...


class UnitOfWork(Protocol):
    ledger: LedgerRepository
    audit: AuditRepository
    idempotency: IdempotencyRepository
    deposits: DepositRepository
    forecasts: ForecastRepository

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


class SchedulingRepository(Protocol):
    """Durable recurring-rule and PostgreSQL outbox boundary."""

    def validate_operation(self, owner_id: UUID, operation: RecurringOperation) -> str | None: ...

    def create_rule(self, rule: RecurringRule, audit_event: AuditEvent) -> RecurringRule: ...

    def get_rule(self, owner_id: UUID, rule_id: UUID) -> RecurringRule | None: ...

    def list_rules(self, owner_id: UUID) -> tuple[RecurringRule, ...]: ...

    def save_rule(
        self,
        rule: RecurringRule,
        *,
        expected_version: int,
        audit_event: AuditEvent,
    ) -> RecurringRule: ...

    def materialize_due(self, now: Instant, *, limit: int) -> int: ...

    def claim_jobs(
        self,
        now: Instant,
        *,
        worker_id: str,
        lease_duration: timedelta,
        limit: int,
    ) -> tuple[OutboxJob, ...]: ...

    def complete_job(
        self,
        job_id: UUID,
        *,
        worker_id: str,
        transaction_id: UUID,
        completed_at: Instant,
    ) -> None: ...

    def fail_job(
        self,
        job_id: UUID,
        *,
        worker_id: str,
        failed_at: Instant,
        error: str,
        base_backoff: timedelta,
    ) -> None: ...

    def list_dead_letters(self, owner_id: UUID) -> tuple[OutboxJob, ...]: ...

    def retry_dead_letter(
        self,
        owner_id: UUID,
        job_id: UUID,
        *,
        retried_at: Instant,
        audit_event: AuditEvent,
    ) -> OutboxJob | None: ...


@dataclass(frozen=True, slots=True)
class AdviceProviderCapabilities:
    json_schema: bool
    system_messages: bool
    non_thinking: bool


@dataclass(frozen=True, slots=True)
class AdviceProviderDescriptor:
    provider: str
    model: str | None
    endpoint_scope: str


@dataclass(frozen=True, slots=True)
class AdviceMessage:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class AdvicePrompt:
    version: str
    messages: tuple[AdviceMessage, ...]
    response_schema: dict[str, object]
    max_tokens: int


@dataclass(frozen=True, slots=True)
class AdviceProviderResponse:
    payload: dict[str, object]


class AdviceProviderError(Exception):
    """Safe provider failure without upstream body, URL, credentials, or user data."""

    def __init__(
        self,
        code: str,
        *,
        retryable: bool = False,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


class AdviceProvider(Protocol):
    @property
    def descriptor(self) -> AdviceProviderDescriptor: ...

    @property
    def capabilities(self) -> AdviceProviderCapabilities: ...

    def generate(self, prompt: AdvicePrompt) -> AdviceProviderResponse: ...
