from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from financial_analytics_app.deposit_ledger import (
    actual_interest,
    principal_cashflows,
    reconcile_interest,
)
from financial_analytics_app.ledger import ResourceConflictError, ResourceNotFoundError
from financial_analytics_app.ports import (
    AuditEvent,
    IdempotencyRecord,
    UnitOfWork,
    UnitOfWorkFactory,
)
from financial_analytics_app.services import IdempotencyConflictError
from financial_analytics_domain import (
    Account,
    AccountKind,
    DepositCashflow,
    DepositProjection,
    DepositTerms,
    Instant,
    Money,
    Transaction,
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
    earned_interest: Money
    ledger_balance: Money


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
        initial_balance: Money | None = None,
        opening_occurred_at: Instant | None = None,
    ) -> DepositTerms:
        with self._uow_factory.open(terms.owner_id) as uow:
            replay_id = self._lock_and_replay(uow, "create_deposit", idempotency_key, request_hash)
            if replay_id is not None:
                replay = uow.deposits.get(replay_id)
                if replay is None:
                    raise RuntimeError("idempotency record points to a missing deposit")
                return replay
            account = uow.ledger.get_account(terms.principal_account_id)
            if account is None:
                account = Account(
                    id=terms.principal_account_id,
                    owner_id=terms.owner_id,
                    name=terms.name,
                    kind=AccountKind.DEPOSIT,
                    currency=terms.currency,
                )
                uow.ledger.add_account(account)
                self._audit(
                    uow,
                    actor_id,
                    "ledger.account_created",
                    account.id,
                    request_id,
                    {"kind": AccountKind.DEPOSIT.value, "internal": True},
                    aggregate_type="account",
                )
            elif account.kind is not AccountKind.DEPOSIT:
                raise ResourceNotFoundError("deposit principal account was not found")
            if account.archived:
                raise ResourceConflictError("archived account cannot back a deposit")
            if account.currency != terms.currency:
                raise ResourceConflictError("deposit and principal account currencies differ")
            uow.deposits.add(terms)
            if initial_balance is not None and initial_balance.amount != 0:
                if opening_occurred_at is None:
                    raise ResourceConflictError("deposit opening balance requires a timestamp")
                now = self._clock()
                if terms.opened_on == now.value.astimezone(ZoneInfo(terms.timezone)).date():
                    opening_occurred_at = Instant(min(opening_occurred_at.value, now.value))
                if initial_balance.currency != terms.currency or initial_balance.amount <= 0:
                    raise ResourceConflictError(
                        "deposit opening balance must be positive in deposit currency"
                    )
                equity, created = uow.ledger.get_or_create_system_account(
                    AccountKind.SYSTEM_EQUITY, terms.currency
                )
                if created:
                    self._audit(
                        uow,
                        actor_id,
                        "ledger.system_account_created",
                        equity.id,
                        request_id,
                        {"kind": equity.kind.value, "currency": terms.currency.code},
                        aggregate_type="account",
                    )
                opening = Transaction.adjustment(
                    id=self._uuid_factory(),
                    owner_id=terms.owner_id,
                    asset=account,
                    equity_account=equity,
                    amount=initial_balance,
                    occurred_at=opening_occurred_at,
                    posting_ids=(self._uuid_factory(), self._uuid_factory()),
                    description="Opening deposit balance",
                    entry_source="system",
                )
                uow.ledger.add_transaction(opening, actor_id=actor_id, request_id=request_id)
                self._audit(
                    uow,
                    actor_id,
                    "deposit.opening_balance_recorded",
                    opening.id,
                    request_id,
                    {"deposit_id": str(terms.id)},
                    aggregate_type="transaction",
                )
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
            reconcile_interest(
                uow,
                terms,
                now=self._clock(),
                actor_id=actor_id,
                uuid_factory=self._uuid_factory,
                request_id=request_id,
            )
            uow.commit()
            return terms

    def list(self, owner_id: UUID) -> tuple[DepositTerms, ...]:
        with self._uow_factory.open(owner_id) as uow:
            return uow.deposits.list()

    def get(self, owner_id: UUID, deposit_id: UUID) -> DepositTerms:
        with self._uow_factory.open(owner_id) as uow:
            return self._require_deposit(uow, deposit_id)

    def update(
        self,
        *,
        terms: DepositTerms,
        actor_id: UUID,
        expected_version: int,
        request_id: UUID | None,
    ) -> DepositTerms:
        with self._uow_factory.open(terms.owner_id) as uow:
            uow.idempotency.lock("deposit_reconciliation", str(terms.id))
            previous = self._require_deposit(uow, terms.id)
            if previous.version != expected_version:
                raise ResourceConflictError("deposit version is stale")
            if previous.principal_account_id != terms.principal_account_id:
                raise ResourceConflictError("deposit principal account cannot be replaced")
            if previous.currency != terms.currency:
                raise ResourceConflictError("deposit currency cannot be changed")
            if terms.automatic_interest and any(
                item.id != terms.id and item.principal_account_id == terms.principal_account_id
                for item in uow.deposits.list()
            ):
                raise ResourceConflictError(
                    "archive duplicate legacy deposits before enabling automatic interest"
                )
            transactions = uow.ledger.list_deposit_transactions(terms.id)
            cashflows = principal_cashflows(terms, transactions)
            project_deposit(terms, cashflows, as_of=terms.opened_on)
            saved = uow.deposits.save(terms, expected_version=expected_version)
            account = uow.ledger.get_account(saved.principal_account_id)
            if account is None:
                raise RuntimeError("deposit principal account disappeared")
            if account.name != saved.name:
                uow.ledger.save_account(replace(account, name=saved.name))
            self._audit(
                uow,
                actor_id,
                "deposit.terms_updated",
                saved.id,
                request_id,
                {"before": self._terms_snapshot(previous), "after": self._terms_snapshot(saved)},
            )
            reconcile_interest(
                uow,
                saved,
                now=self._clock(),
                actor_id=actor_id,
                uuid_factory=self._uuid_factory,
                request_id=request_id,
            )
            uow.commit()
            return saved

    def archive(
        self,
        *,
        owner_id: UUID,
        actor_id: UUID,
        deposit_id: UUID,
        expected_version: int,
        request_id: UUID | None,
    ) -> DepositTerms:
        with self._uow_factory.open(owner_id) as uow:
            uow.idempotency.lock("deposit_reconciliation", str(deposit_id))
            previous = self._require_deposit(uow, deposit_id)
            if previous.version != expected_version:
                raise ResourceConflictError("deposit version is stale")
            saved = uow.deposits.save(
                replace(previous, archived=True), expected_version=expected_version
            )
            account = uow.ledger.get_account(saved.principal_account_id)
            if account is None:
                raise RuntimeError("deposit principal account disappeared")
            if not account.archived and not any(
                item.id != saved.id and item.principal_account_id == saved.principal_account_id
                for item in uow.deposits.list()
            ):
                uow.ledger.save_account(replace(account, archived=True))
            self._audit(
                uow,
                actor_id,
                "deposit.archived",
                saved.id,
                request_id,
                {"previous_version": expected_version, "version": saved.version},
            )
            uow.commit()
            return saved

    def accrue_due(self, owner_id: UUID) -> None:
        with self._uow_factory.open(owner_id) as uow:
            for terms in sorted(uow.deposits.list(), key=lambda item: item.id):
                reconcile_interest(
                    uow,
                    terms,
                    now=self._clock(),
                    actor_id=owner_id,
                    uuid_factory=self._uuid_factory,
                )
            uow.commit()

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
            cashflows = principal_cashflows(terms, transactions)
            actual_by_date = actual_interest(terms, transactions)
            evaluation_date = max(terms.opened_on, min(as_of, close_on or terms.matures_on))
            projection = project_deposit(
                terms,
                cashflows,
                as_of=evaluation_date,
                close_on=close_on,
            )
            contributed = sum(
                (
                    flow.amount.amount
                    for flow in cashflows
                    if effective_cashflow_date(terms, flow) < evaluation_date
                ),
                start=Decimal(0),
            )
            earned = Money.of(projection.current_value.amount - contributed, terms.currency)
            ledger_balance = Money.of(
                sum(
                    (
                        posting.amount.amount
                        for transaction in transactions
                        if transaction.occurred_at.value.astimezone(ZoneInfo(terms.timezone)).date()
                        <= as_of
                        for posting in transaction.postings
                        if posting.account_id == terms.principal_account_id
                    ),
                    start=Decimal(0),
                ),
                terms.currency,
            )
            projection = replace(
                projection,
                as_of=as_of,
                accrued_interest=(
                    Money.of("0", terms.currency)
                    if evaluation_date == projection.closes_on
                    else projection.accrued_interest
                ),
                current_value=(
                    ledger_balance
                    if evaluation_date == projection.closes_on
                    else ledger_balance + projection.accrued_interest
                ),
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
            return DepositValuation(projection, rows, earned, ledger_balance)

    @staticmethod
    def _require_deposit(uow: UnitOfWork, deposit_id: UUID) -> DepositTerms:
        terms = uow.deposits.get(deposit_id)
        if terms is None or terms.archived:
            raise ResourceNotFoundError("deposit was not found")
        return terms

    @staticmethod
    def _terms_snapshot(terms: DepositTerms) -> dict[str, object]:
        return {
            "name": terms.name,
            "opened_on": terms.opened_on.isoformat(),
            "matures_on": terms.matures_on.isoformat(),
            "rates": [
                {
                    "starts_on": period.starts_on.isoformat(),
                    "ends_on": period.ends_on.isoformat(),
                    "nominal_rate": format(period.nominal_rate.value, "f"),
                }
                for period in terms.rate_periods
            ],
            "capitalization_frequency": terms.capitalization_frequency.value,
            "day_count_convention": terms.day_count_convention.value,
            "rounding_policy": terms.rounding_policy.value,
            "interest_rounding_frequency": terms.interest_rounding_frequency.value,
            "timezone": terms.timezone,
            "cashflow_cutoff_time": terms.cashflow_cutoff_time.isoformat(),
            "cashflow_cutoff_inclusive": terms.cashflow_cutoff_inclusive,
            "early_close_policy": terms.early_close_rule.policy.value,
            "early_close_rate": (
                None
                if terms.early_close_rule.nominal_rate is None
                else str(terms.early_close_rule.nominal_rate.value)
            ),
            "tax_rate": format(terms.tax_rate.value, "f"),
            "archived": terms.archived,
            "version": terms.version,
            "automatic_interest": terms.automatic_interest,
        }

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
        if transaction.kind.value != "interest" and transaction.deposit_id is not None:
            terms = self._require_deposit(uow, transaction.deposit_id)
            reconcile_interest(
                uow,
                terms,
                now=self._clock(),
                actor_id=actor_id,
                uuid_factory=self._uuid_factory,
                request_id=request_id,
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
