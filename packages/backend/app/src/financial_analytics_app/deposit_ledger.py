"""Shared deposit/ledger reconciliation, without transport or persistence dependencies."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from financial_analytics_app.ports import AuditEvent, UnitOfWork
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
from financial_analytics_domain.errors import DomainError


def principal_cashflows(
    terms: DepositTerms, transactions: tuple[Transaction, ...]
) -> tuple[DepositCashflow, ...]:
    """Canceled postings are excluded from the corrected calculation history."""
    reversed_ids = {
        item.reversal_of_id for item in transactions if item.kind is TransactionKind.REVERSAL
    }
    result = []
    for transaction in transactions:
        if transaction.id in reversed_ids or transaction.kind in {
            TransactionKind.INTEREST,
            TransactionKind.REVERSAL,
        }:
            continue
        amount = next(
            posting.amount
            for posting in transaction.postings
            if posting.account_id == terms.principal_account_id
        )
        flow = DepositCashflow(transaction.id, transaction.occurred_at, amount)
        effective_on = effective_cashflow_date(terms, flow)
        # Legacy opening balances may predate the contract. They are capital at opening.
        if effective_on < terms.opened_on:
            flow = replace(
                flow,
                occurred_at=Instant(
                    datetime.combine(terms.opened_on, time.min, tzinfo=ZoneInfo(terms.timezone))
                ),
            )
        if effective_on < terms.matures_on:
            result.append(flow)
    return tuple(result)


def actual_interest(
    terms: DepositTerms, transactions: tuple[Transaction, ...]
) -> dict[date, Decimal]:
    by_id = {item.id: item for item in transactions}
    result: defaultdict[date, Decimal] = defaultdict(Decimal)
    for transaction in transactions:
        original = by_id.get(transaction.reversal_of_id) if transaction.reversal_of_id else None
        kind = original.kind if original is not None else transaction.kind
        if kind is not TransactionKind.INTEREST:
            continue
        # A reversal corrects the same interest period, regardless of when it was entered.
        occurred_at = original.occurred_at if original is not None else transaction.occurred_at
        posting_date = occurred_at.value.astimezone(ZoneInfo(terms.timezone)).date()
        result[posting_date] += next(
            posting.amount.amount
            for posting in transaction.postings
            if posting.account_id == terms.principal_account_id
        )
    return dict(result)


def reconcile_interest(
    uow: UnitOfWork,
    terms: DepositTerms,
    *,
    now: Instant,
    actor_id: UUID,
    uuid_factory: Callable[[], UUID],
    request_id: UUID | None = None,
) -> DepositProjection:
    """Append only the difference between due calculated and posted interest."""
    uow.idempotency.lock("deposit_reconciliation", str(terms.id))
    latest = uow.deposits.get(terms.id)
    if latest is not None:
        terms = latest
    transactions = uow.ledger.list_deposit_transactions(terms.id)
    today = now.value.astimezone(ZoneInfo(terms.timezone)).date()
    as_of = max(terms.opened_on, min(today, terms.matures_on))
    projection = project_deposit(terms, principal_cashflows(terms, transactions), as_of=as_of)
    if not terms.automatic_interest:
        return projection
    expected = {
        entry.posting_date: entry.net_interest.amount
        for entry in projection.schedule
        if entry.posting_date <= today
    }
    actual = actual_interest(terms, transactions)
    principal = uow.ledger.get_account(terms.principal_account_id)
    if principal is None:
        raise RuntimeError("deposit principal account disappeared")
    for posting_date in sorted(expected.keys() | actual.keys()):
        if posting_date > today:
            continue
        difference = expected.get(posting_date, Decimal(0)) - actual.get(posting_date, Decimal(0))
        if difference == 0:
            continue
        income, created = uow.ledger.get_or_create_system_account(
            AccountKind.SYSTEM_INCOME, terms.currency
        )
        if created:
            uow.audit.append(
                AuditEvent(
                    id=uuid_factory(),
                    owner_id=terms.owner_id,
                    actor_id=actor_id,
                    event_type="ledger.system_account_created",
                    aggregate_type="account",
                    aggregate_id=income.id,
                    occurred_at=now,
                    request_id=request_id,
                )
            )
        transaction = Transaction.deposit_interest(
            id=uuid_factory(),
            owner_id=terms.owner_id,
            deposit_id=terms.id,
            principal_account=principal,
            income_account=income,
            amount=Money.of(difference, terms.currency),
            occurred_at=Instant(
                datetime.combine(posting_date, time.min, tzinfo=ZoneInfo(terms.timezone))
            ),
            posting_ids=(uuid_factory(), uuid_factory()),
            description="Автоматическое начисление процентов"
            if difference > 0
            else "Перерасчёт процентов",
        )
        uow.ledger.add_transaction(transaction, actor_id=actor_id, request_id=request_id)
        uow.audit.append(
            AuditEvent(
                id=uuid_factory(),
                owner_id=terms.owner_id,
                actor_id=actor_id,
                event_type="deposit.interest_reconciled",
                aggregate_type="transaction",
                aggregate_id=transaction.id,
                occurred_at=now,
                request_id=request_id,
                payload={
                    "deposit_id": str(terms.id),
                    "terms_version": terms.version,
                    "posting_date": posting_date.isoformat(),
                    "amount": str(difference),
                },
            )
        )
    return projection


def validate_deposit_posting(terms: DepositTerms, transaction: Transaction) -> None:
    local_date = transaction.occurred_at.value.astimezone(ZoneInfo(terms.timezone)).date()
    if local_date < terms.opened_on:
        raise DomainError("deposit operation cannot precede its opening date")
