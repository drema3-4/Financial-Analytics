from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from financial_analytics_app.ledger import ResourceConflictError, ResourceNotFoundError
from financial_analytics_app.ports import (
    AuditEvent,
    IdempotencyRecord,
    UnitOfWork,
    UnitOfWorkFactory,
)
from financial_analytics_app.services import IdempotencyConflictError
from financial_analytics_domain import (
    AccountKind,
    DepositCashflow,
    DepositProjection,
    DepositTerms,
    Instant,
    Money,
    Transaction,
    TransactionKind,
    effective_cashflow_date,
    project_deposit,
)


@dataclass(frozen=True, slots=True)
class InterestReconciliation:
    posting_date: date
    planned_interest: Money
    actual_interest: Money
    variance: Money


@dataclass(frozen=True, slots=True)
class DepositValuation:
    projection: DepositProjection
    reconciliation: tuple[InterestReconciliation, ...]


class DepositService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        uuid_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], Instant] = Instant.now,
    ) -> None:
        self._uow_factory = uow_factory
        self._uuid_factory = uuid_factory
        self._clock = clock

    def create(
        self,
        *,
        terms: DepositTerms,
        actor_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: UUID | None,
    ) -> DepositTerms:
        with self._uow_factory.open(terms.owner_id) as uow:
            replay_id = self._lock_and_replay(uow, "create_deposit", idempotency_key, request_hash)
            if replay_id is not None:
                replay = uow.deposits.get(replay_id)
                if replay is None:
                    raise RuntimeError("idempotency record points to a missing deposit")
                return replay
            account = uow.ledger.get_account(terms.principal_account_id)
            if account is None or account.kind is not AccountKind.DEPOSIT:
                raise ResourceNotFoundError("deposit principal account was not found")
            if account.archived:
                raise ResourceConflictError("archived account cannot back a deposit")
            if account.currency != terms.currency:
                raise ResourceConflictError("deposit and principal account currencies differ")
            uow.deposits.add(terms)
            self._audit(
                uow,
                actor_id,
                "deposit.terms_created",
                terms.id,
                request_id,
                {"algorithm_version": terms.algorithm_version},
            )
            self._remember(
                uow,
                terms.owner_id,
                "create_deposit",
                idempotency_key,
                request_hash,
                "deposit",
                terms.id,
            )
            uow.commit()
            return terms

    def list(self, owner_id: UUID) -> tuple[DepositTerms, ...]:
        with self._uow_factory.open(owner_id) as uow:
            return uow.deposits.list()

    def get(self, owner_id: UUID, deposit_id: UUID) -> DepositTerms:
        with self._uow_factory.open(owner_id) as uow:
            return self._require_deposit(uow, deposit_id)

    def record_cashflow(
        self,
        *,
        owner_id: UUID,
        actor_id: UUID,
        deposit_id: UUID,
        counterparty_account_id: UUID,
        amount: Money,
        occurred_at: Instant,
        description: str,
        idempotency_key: str,
        request_hash: str,
        request_id: UUID | None,
    ) -> Transaction:
        with self._uow_factory.open(owner_id) as uow:
            replay = self._transaction_replay(
                uow, "create_deposit_cashflow", idempotency_key, request_hash
            )
            if replay is not None:
                return replay
            terms = self._require_deposit(uow, deposit_id)
            principal = uow.ledger.get_account(terms.principal_account_id)
            counterparty = uow.ledger.get_account(counterparty_account_id)
            if principal is None or counterparty is None or not counterparty.kind.is_asset:
                raise ResourceNotFoundError("deposit cashflow account was not found")
            if principal.archived or counterparty.archived:
                raise ResourceConflictError("archived accounts cannot receive deposit cashflows")
            if amount.currency != terms.currency:
                raise ResourceConflictError("deposit cashflow currency differs from terms")
            probe = DepositCashflow(self._uuid_factory(), occurred_at, amount)
            effective_on = effective_cashflow_date(terms, probe)
            if not terms.opened_on <= effective_on < terms.matures_on:
                raise ResourceConflictError("deposit cashflow falls outside the term")
            source, destination = (
                (counterparty, principal) if amount.amount > 0 else (principal, counterparty)
            )
            transaction = Transaction.transfer(
                id=self._uuid_factory(),
                owner_id=owner_id,
                source=source,
                destination=destination,
                amount=Money.of(abs(amount.amount), amount.currency),
                occurred_at=occurred_at,
                posting_ids=(self._uuid_factory(), self._uuid_factory()),
                description=description,
                entry_source="deposit_cashflow",
                deposit_id=deposit_id,
            )
            self._persist_transaction(
                uow,
                transaction,
                actor_id,
                "create_deposit_cashflow",
                idempotency_key,
                request_hash,
                request_id,
                "deposit.cashflow_recorded",
            )
            return transaction

    def record_interest(
        self,
        *,
        owner_id: UUID,
        actor_id: UUID,
        deposit_id: UUID,
        amount: Money,
        occurred_at: Instant,
        description: str,
        idempotency_key: str,
        request_hash: str,
        request_id: UUID | None,
    ) -> Transaction:
        with self._uow_factory.open(owner_id) as uow:
            replay = self._transaction_replay(
                uow, "create_deposit_interest", idempotency_key, request_hash
            )
            if replay is not None:
                return replay
            terms = self._require_deposit(uow, deposit_id)
            principal = uow.ledger.get_account(terms.principal_account_id)
            if principal is None:
                raise ResourceNotFoundError("deposit principal account was not found")
            if amount.currency != terms.currency or amount.amount == 0:
                raise ResourceConflictError("interest must be non-zero in deposit currency")
            income, created = uow.ledger.get_or_create_system_account(
                AccountKind.SYSTEM_INCOME, terms.currency
            )
            if created:
                self._audit(
                    uow,
                    actor_id,
                    "ledger.system_account_created",
                    income.id,
                    request_id,
                    {"kind": income.kind.value, "currency": terms.currency.code},
                    aggregate_type="account",
                )
            transaction = Transaction.deposit_interest(
                id=self._uuid_factory(),
                owner_id=owner_id,
                deposit_id=deposit_id,
                principal_account=principal,
                income_account=income,
                amount=amount,
                occurred_at=occurred_at,
                posting_ids=(self._uuid_factory(), self._uuid_factory()),
                description=description,
            )
            self._persist_transaction(
                uow,
                transaction,
                actor_id,
                "create_deposit_interest",
                idempotency_key,
                request_hash,
                request_id,
                "deposit.interest_recorded",
            )
            return transaction

    def valuation(
        self,
        owner_id: UUID,
        deposit_id: UUID,
        *,
        as_of: date,
        close_on: date | None,
    ) -> DepositValuation:
        with self._uow_factory.open(owner_id) as uow:
            terms = self._require_deposit(uow, deposit_id)
            transactions = uow.ledger.list_deposit_transactions(deposit_id)
            cashflows: list[DepositCashflow] = []
            actual_by_date: defaultdict[date, Decimal] = defaultdict(Decimal)
            zone = ZoneInfo(terms.timezone)
            for transaction in transactions:
                classified = transaction.kind
                if classified is TransactionKind.REVERSAL:
                    if transaction.reversal_of_id is None:
                        raise RuntimeError("reversal is missing its original transaction")
                    original = uow.ledger.get_transaction(transaction.reversal_of_id)
                    if original is None:
                        raise RuntimeError("deposit reversal original is missing")
                    classified = original.kind
                principal_amount = next(
                    posting.amount
                    for posting in transaction.postings
                    if posting.account_id == terms.principal_account_id
                )
                if classified is TransactionKind.TRANSFER:
                    cashflows.append(
                        DepositCashflow(transaction.id, transaction.occurred_at, principal_amount)
                    )
                elif classified is TransactionKind.INTEREST:
                    posting_date = transaction.occurred_at.value.astimezone(zone).date()
                    actual_by_date[posting_date] += principal_amount.amount
            projection = project_deposit(
                terms,
                tuple(cashflows),
                as_of=as_of,
                close_on=close_on,
            )
            planned_by_date = {
                entry.posting_date: entry.net_interest.amount for entry in projection.schedule
            }
            rows = tuple(
                InterestReconciliation(
                    posting_date=posting_date,
                    planned_interest=Money.of(planned_by_date.get(posting_date, 0), terms.currency),
                    actual_interest=Money.of(actual_by_date.get(posting_date, 0), terms.currency),
                    variance=Money.of(
                        actual_by_date.get(posting_date, 0) - planned_by_date.get(posting_date, 0),
                        terms.currency,
                    ),
                )
                for posting_date in sorted(planned_by_date.keys() | actual_by_date.keys())
            )
            return DepositValuation(projection, rows)

    @staticmethod
    def _require_deposit(uow: UnitOfWork, deposit_id: UUID) -> DepositTerms:
        terms = uow.deposits.get(deposit_id)
        if terms is None:
            raise ResourceNotFoundError("deposit was not found")
        return terms

    @staticmethod
    def _lock_and_replay(uow: UnitOfWork, scope: str, key: str, request_hash: str) -> UUID | None:
        uow.idempotency.lock(scope, key)
        existing = uow.idempotency.get(scope, key)
        if existing is None:
            return None
        if existing.request_hash != request_hash:
            raise IdempotencyConflictError(
                "idempotency key was used with a different request payload"
            )
        return existing.resource_id

    def _transaction_replay(
        self, uow: UnitOfWork, scope: str, key: str, request_hash: str
    ) -> Transaction | None:
        resource_id = self._lock_and_replay(uow, scope, key, request_hash)
        if resource_id is None:
            return None
        transaction = uow.ledger.get_transaction(resource_id)
        if transaction is None:
            raise RuntimeError("idempotency record points to a missing transaction")
        return transaction

    def _persist_transaction(
        self,
        uow: UnitOfWork,
        transaction: Transaction,
        actor_id: UUID,
        scope: str,
        idempotency_key: str,
        request_hash: str,
        request_id: UUID | None,
        event_type: str,
    ) -> None:
        uow.ledger.add_transaction(transaction, actor_id=actor_id, request_id=request_id)
        self._audit(uow, actor_id, event_type, transaction.id, request_id)
        self._remember(
            uow,
            transaction.owner_id,
            scope,
            idempotency_key,
            request_hash,
            "transaction",
            transaction.id,
        )
        uow.commit()

    def _remember(
        self,
        uow: UnitOfWork,
        owner_id: UUID,
        scope: str,
        key: str,
        request_hash: str,
        resource_type: str,
        resource_id: UUID,
    ) -> None:
        uow.idempotency.add(
            IdempotencyRecord(
                owner_id=owner_id,
                scope=scope,
                key=key,
                request_hash=request_hash,
                resource_type=resource_type,
                resource_id=resource_id,
                created_at=self._clock(),
            )
        )

    def _audit(
        self,
        uow: UnitOfWork,
        actor_id: UUID,
        event_type: str,
        aggregate_id: UUID,
        request_id: UUID | None,
        payload: dict[str, object] | None = None,
        *,
        aggregate_type: str = "deposit",
    ) -> None:
        uow.audit.append(
            AuditEvent(
                id=self._uuid_factory(),
                owner_id=uow.ledger.owner_id,
                actor_id=actor_id,
                event_type=event_type,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                occurred_at=self._clock(),
                request_id=request_id,
                payload=payload,
            )
        )
