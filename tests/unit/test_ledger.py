from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from financial_analytics_domain import (
    Account,
    AccountKind,
    Category,
    CategoryKind,
    Currency,
    Instant,
    Money,
    Posting,
    Transaction,
    TransactionKind,
    rebuild_balances,
)
from financial_analytics_domain.errors import (
    CurrencyMismatchError,
    OwnershipError,
    UnbalancedTransactionError,
)

OWNER = UUID("00000000-0000-0000-0000-000000000001")
OTHER_OWNER = UUID("00000000-0000-0000-0000-000000000002")
NOW = Instant(datetime(2026, 10, 13, tzinfo=UTC))
RUB = Currency("RUB")


def account(kind: AccountKind, *, owner_id: UUID = OWNER, currency: Currency = RUB) -> Account:
    return Account(uuid4(), owner_id, kind.value, currency, kind)


def category(kind: CategoryKind, *, owner_id: UUID = OWNER) -> Category:
    return Category(uuid4(), owner_id, kind.value, kind)


def test_unbalanced_transaction_cannot_be_constructed() -> None:
    transaction_id = uuid4()
    with pytest.raises(UnbalancedTransactionError):
        Transaction(
            id=transaction_id,
            owner_id=OWNER,
            kind=TransactionKind.TRANSFER,
            currency=RUB,
            occurred_at=NOW,
            postings=(
                Posting(uuid4(), transaction_id, uuid4(), Money.of("-10", RUB)),
                Posting(uuid4(), transaction_id, uuid4(), Money.of("9.99", RUB)),
            ),
        )


def test_transfer_rejects_currency_mismatch_and_cross_owner_accounts() -> None:
    source = account(AccountKind.BANK)

    with pytest.raises(CurrencyMismatchError):
        Transaction.transfer(
            id=uuid4(),
            owner_id=OWNER,
            source=source,
            destination=account(AccountKind.CASH, currency=Currency("USD")),
            amount=Money.of("1", RUB),
            occurred_at=NOW,
            posting_ids=(uuid4(), uuid4()),
        )
    with pytest.raises(OwnershipError):
        Transaction.transfer(
            id=uuid4(),
            owner_id=OWNER,
            source=source,
            destination=account(AccountKind.CASH, owner_id=OTHER_OWNER),
            amount=Money.of("1", RUB),
            occurred_at=NOW,
            posting_ids=(uuid4(), uuid4()),
        )


@given(
    st.decimals(
        min_value=Decimal("0.01"),
        max_value=Decimal("999999999.99"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    )
)
def test_property_transfer_postings_always_balance(value: Decimal) -> None:
    transaction = Transaction.transfer(
        id=uuid4(),
        owner_id=OWNER,
        source=account(AccountKind.BANK),
        destination=account(AccountKind.SAVINGS),
        amount=Money(value, RUB),
        occurred_at=NOW,
        posting_ids=(uuid4(), uuid4()),
    )

    assert sum(posting.amount.amount for posting in transaction.postings) == 0


@given(
    st.decimals(
        min_value=Decimal("0.01"),
        max_value=Decimal("999999.99"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    )
)
def test_property_reversal_exactly_restores_balances(value: Decimal) -> None:
    source = account(AccountKind.BANK)
    destination = account(AccountKind.SAVINGS)
    original = Transaction.transfer(
        id=uuid4(),
        owner_id=OWNER,
        source=source,
        destination=destination,
        amount=Money(value, RUB),
        occurred_at=NOW,
        posting_ids=(uuid4(), uuid4()),
    )
    reversal = Transaction.reversal(
        id=uuid4(),
        owner_id=OWNER,
        original=original,
        occurred_at=NOW,
        posting_ids=(uuid4(), uuid4()),
        reason="Correction",
    )

    balances = rebuild_balances((source, destination), (original, reversal))

    assert balances[source.id] == Money.of("0", RUB)
    assert balances[destination.id] == Money.of("0", RUB)
    assert reversal.reversal_of_id == original.id
    assert {posting.reversal_of_id for posting in reversal.postings} == {
        posting.id for posting in original.postings
    }


def test_income_expense_transfer_and_reversal_rebuild_from_postings() -> None:
    cash = account(AccountKind.CASH)
    bank = account(AccountKind.BANK)
    income_side = account(AccountKind.SYSTEM_INCOME)
    expense_side = account(AccountKind.SYSTEM_EXPENSE)
    income = Transaction.income(
        id=uuid4(),
        owner_id=OWNER,
        asset=bank,
        income_account=income_side,
        category=category(CategoryKind.INCOME),
        amount=Money.of("1000", RUB),
        occurred_at=NOW,
        posting_ids=(uuid4(), uuid4()),
    )
    expense = Transaction.expense(
        id=uuid4(),
        owner_id=OWNER,
        asset=bank,
        expense_account=expense_side,
        category=category(CategoryKind.EXPENSE),
        amount=Money.of("125.25", RUB),
        occurred_at=NOW,
        posting_ids=(uuid4(), uuid4()),
    )
    transfer = Transaction.transfer(
        id=uuid4(),
        owner_id=OWNER,
        source=bank,
        destination=cash,
        amount=Money.of("200", RUB),
        occurred_at=NOW,
        posting_ids=(uuid4(), uuid4()),
    )
    reversal = Transaction.reversal(
        id=uuid4(),
        owner_id=OWNER,
        original=expense,
        occurred_at=NOW,
        posting_ids=(uuid4(), uuid4()),
        reason="Wrong receipt",
    )

    balances = rebuild_balances(
        (cash, bank, income_side, expense_side),
        (income, expense, transfer, reversal),
    )

    assert balances[bank.id] == Money.of("800", RUB)
    assert balances[cash.id] == Money.of("200", RUB)
    assert balances[income_side.id] == Money.of("-1000", RUB)
    assert balances[expense_side.id] == Money.of("0", RUB)
