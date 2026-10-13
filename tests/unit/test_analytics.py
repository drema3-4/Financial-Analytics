from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest

from financial_analytics_domain import (
    Account,
    AccountKind,
    AnalyticsPeriod,
    Category,
    CategoryGroup,
    CategoryKind,
    Currency,
    CurrencyMode,
    Instant,
    Money,
    PeriodGranularity,
    Transaction,
    build_analytics_report,
    local_midnight,
)
from financial_analytics_domain.errors import DomainError, OwnershipError

OWNER = UUID("00000000-0000-0000-0000-000000000001")
OTHER_OWNER = UUID("00000000-0000-0000-0000-000000000002")
RUB = Currency("RUB")
USD = Currency("USD")


def _account(kind: AccountKind, currency: Currency = RUB) -> Account:
    return Account(uuid4(), OWNER, kind.value, currency, kind)


def _at(value: str) -> Instant:
    return Instant(datetime.fromisoformat(value))


def _income(
    asset: Account,
    system: Account,
    category: Category,
    amount: str,
    occurred_at: str,
) -> Transaction:
    return Transaction.income(
        id=uuid4(),
        owner_id=OWNER,
        asset=asset,
        income_account=system,
        category=category,
        amount=Money.of(amount, asset.currency),
        occurred_at=_at(occurred_at),
        posting_ids=(uuid4(), uuid4()),
    )


def _expense(
    asset: Account,
    system: Account,
    category: Category,
    amount: str,
    occurred_at: str,
) -> Transaction:
    return Transaction.expense(
        id=uuid4(),
        owner_id=OWNER,
        asset=asset,
        expense_account=system,
        category=category,
        amount=Money.of(amount, asset.currency),
        occurred_at=_at(occurred_at),
        posting_ids=(uuid4(), uuid4()),
    )


def test_reconciled_metrics_transfers_reversals_breakdowns_and_mixed_currency() -> None:
    bank = _account(AccountKind.BANK)
    cash = _account(AccountKind.CASH)
    income_side = _account(AccountKind.SYSTEM_INCOME)
    expense_side = _account(AccountKind.SYSTEM_EXPENSE)
    equity = _account(AccountKind.SYSTEM_EQUITY)
    usd_bank = _account(AccountKind.BANK, USD)
    usd_income_side = _account(AccountKind.SYSTEM_INCOME, USD)
    group = CategoryGroup(uuid4(), OWNER, "Household")
    salary = Category(uuid4(), OWNER, "Salary", CategoryKind.INCOME)
    rent = Category(uuid4(), OWNER, "Rent", CategoryKind.EXPENSE, group.id, is_mandatory=True)
    food = Category(uuid4(), OWNER, "Food", CategoryKind.EXPENSE, group.id)
    usd_salary = Category(uuid4(), OWNER, "USD salary", CategoryKind.INCOME)
    income = _income(bank, income_side, salary, "1000.00", "2026-10-02T10:00:00+04:00")
    mandatory_expense = _expense(bank, expense_side, rent, "300.00", "2026-10-03T10:00:00+04:00")
    corrected_expense = _expense(bank, expense_side, food, "100.00", "2026-10-04T10:00:00+04:00")
    reversal = Transaction.reversal(
        id=uuid4(),
        owner_id=OWNER,
        original=corrected_expense,
        occurred_at=_at("2026-10-05T10:00:00+04:00"),
        posting_ids=(uuid4(), uuid4()),
        reason="Correction",
    )
    transfer = Transaction.transfer(
        id=uuid4(),
        owner_id=OWNER,
        source=bank,
        destination=cash,
        amount=Money.of("200.00", RUB),
        occurred_at=_at("2026-10-06T10:00:00+04:00"),
        posting_ids=(uuid4(), uuid4()),
    )
    adjustment = Transaction.adjustment(
        id=uuid4(),
        owner_id=OWNER,
        asset=bank,
        equity_account=equity,
        amount=Money.of("50.00", RUB),
        occurred_at=_at("2026-10-07T10:00:00+04:00"),
        posting_ids=(uuid4(), uuid4()),
        description="Statement correction",
    )
    usd_income = _income(
        usd_bank, usd_income_side, usd_salary, "10.00", "2026-10-08T10:00:00+04:00"
    )

    report = build_analytics_report(
        accounts=(bank, cash, income_side, expense_side, equity, usd_bank, usd_income_side),
        categories=(salary, rent, food, usd_salary),
        groups=(group,),
        transactions=(
            income,
            mandatory_expense,
            corrected_expense,
            reversal,
            transfer,
            adjustment,
            usd_income,
        ),
        period=AnalyticsPeriod(
            date(2026, 10, 1),
            date(2026, 11, 1),
            "Europe/Saratov",
            PeriodGranularity.MONTH,
        ),
        now=datetime(2026, 11, 2, tzinfo=UTC),
    )

    assert report.currency_mode is CurrencyMode.SEPARATED
    assert report.combined_currency is None
    rub = next(item for item in report.totals if item.currency == RUB)
    assert rub.income.value == Money.of("1000.00", RUB)
    assert rub.expense.value == Money.of("300.00", RUB)
    assert rub.cash_flow.value == Money.of("700.00", RUB)
    assert rub.savings_rate.value == Money.of("0.70", RUB).amount
    assert rub.mandatory_expense.value == Money.of("300.00", RUB)
    assert rub.mandatory_expense_share.value == Money.of("1.00", RUB).amount
    assert rub.closing_net_worth.value == Money.of("750.00", RUB)
    assert transfer.id not in rub.cash_flow.evidence.transaction_ids
    assert adjustment.id not in rub.cash_flow.evidence.transaction_ids
    assert (
        sum(item.amount.amount for item in rub.category_breakdown if item.flow_type == "income")
        == rub.income.value.amount
    )
    assert (
        sum(item.amount.amount for item in rub.category_breakdown if item.flow_type == "expense")
        == rub.expense.value.amount
    )
    assert (
        sum(item.amount.amount for item in rub.group_breakdown if item.flow_type == "expense")
        == rub.expense.value.amount
    )
    assert (
        corrected_expense.id
        in next(
            item for item in rub.category_breakdown if item.name == "Food"
        ).evidence.transaction_ids
    )
    assert (
        reversal.id
        in next(
            item for item in rub.category_breakdown if item.name == "Food"
        ).evidence.transaction_ids
    )


def test_timezone_boundaries_empty_buckets_and_open_period_are_explicit() -> None:
    bank = _account(AccountKind.BANK)
    income_side = _account(AccountKind.SYSTEM_INCOME)
    salary = Category(uuid4(), OWNER, "Salary", CategoryKind.INCOME)
    transaction = _income(
        bank,
        income_side,
        salary,
        "25.00",
        "2026-03-08T00:30:00-05:00",
    )
    period = AnalyticsPeriod(
        date(2026, 3, 7),
        date(2026, 3, 10),
        "America/New_York",
        PeriodGranularity.DAY,
    )

    report = build_analytics_report(
        accounts=(bank, income_side),
        categories=(salary,),
        groups=(),
        transactions=(transaction,),
        period=period,
        now=datetime(2026, 3, 9, 12, tzinfo=UTC),
    )

    assert (
        local_midnight(date(2026, 3, 9), period.timezone)
        - local_midnight(date(2026, 3, 8), period.timezone)
    ).total_seconds() == pytest.approx(23 * 60 * 60)
    assert len(report.buckets) == 3
    assert [item.is_complete for item in report.buckets] == [True, True, False]
    assert report.buckets[0].currencies[0].income.value == Money.of("0.00", RUB)
    assert report.buckets[1].currencies[0].income.value == Money.of("25.00", RUB)
    assert report.comparison.current_is_complete is False
    assert all(item.bucket_start != date(2026, 3, 9) for item in report.anomalies)


def test_deterministic_anomaly_returns_baseline_deviation_threshold_and_evidence() -> None:
    bank = _account(AccountKind.BANK)
    expense_side = _account(AccountKind.SYSTEM_EXPENSE)
    groceries = Category(uuid4(), OWNER, "Groceries", CategoryKind.EXPENSE)
    transactions = tuple(
        _expense(
            bank,
            expense_side,
            groceries,
            "100.00" if day < 7 else "200.00",
            f"2026-10-{day:02d}T10:00:00+04:00",
        )
        for day in range(1, 8)
    )

    report = build_analytics_report(
        accounts=(bank, expense_side),
        categories=(groceries,),
        groups=(),
        transactions=transactions,
        period=AnalyticsPeriod(
            date(2026, 10, 7),
            date(2026, 10, 8),
            "Europe/Saratov",
            PeriodGranularity.DAY,
        ),
        now=datetime(2026, 10, 9, tzinfo=UTC),
    )

    assert len(report.anomalies) == 1
    anomaly = report.anomalies[0]
    assert anomaly.metric == "expense"
    assert anomaly.direction == "increase"
    assert anomaly.observed == Money.of("200.00", RUB)
    assert anomaly.baseline == Money.of("100.00", RUB)
    assert anomaly.deviation == Money.of("100.00", RUB)
    assert anomaly.threshold == Money.of("50.00", RUB)
    assert anomaly.baseline_bucket_count == 6
    assert anomaly.evidence.transaction_ids == (transactions[-1].id,)


def test_invalid_mandatory_income_alignment_and_cross_owner_input_are_rejected() -> None:
    with pytest.raises(DomainError):
        Category(uuid4(), OWNER, "Salary", CategoryKind.INCOME, is_mandatory=True)
    with pytest.raises(DomainError):
        AnalyticsPeriod(
            date(2026, 10, 2),
            date(2026, 11, 1),
            "UTC",
            PeriodGranularity.MONTH,
        )
    own = _account(AccountKind.BANK)
    foreign = Account(uuid4(), OTHER_OWNER, "Foreign", RUB, AccountKind.BANK)
    with pytest.raises(OwnershipError):
        build_analytics_report(
            accounts=(own, foreign),
            categories=(),
            groups=(),
            transactions=(),
            period=AnalyticsPeriod(
                date(2026, 10, 1),
                date(2026, 10, 2),
                "UTC",
                PeriodGranularity.DAY,
            ),
            now=datetime(2026, 10, 3, tzinfo=UTC),
        )
