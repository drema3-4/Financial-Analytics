from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from uuid import UUID

from hypothesis import given
from hypothesis import strategies as st

from financial_analytics_app.forecast import _recurring_cashflows
from financial_analytics_domain import (
    CatchUpPolicy,
    Currency,
    FinancialGoal,
    ForecastAccount,
    ForecastAssumptions,
    ForecastCashflow,
    ForecastFlowKind,
    ForecastInputSnapshot,
    HistoricalExpenseSample,
    Instant,
    MissingDayPolicy,
    Money,
    OneTimeCashflow,
    Rate,
    RecurrenceFrequency,
    RecurringOperation,
    RecurringRule,
    RecurringRuleStatus,
    TransactionKind,
    forecast_finances,
    plan_goals,
)

OWNER = UUID("00000000-0000-0000-0000-000000000001")
ACCOUNT = UUID("00000000-0000-0000-0000-000000000010")
SECOND_ACCOUNT = UUID("00000000-0000-0000-0000-000000000011")
RUB = Currency("RUB")
CAPTURED = Instant(datetime(2026, 1, 1, tzinfo=UTC))


def _snapshot(
    *,
    balance: str = "1000.00",
    cashflows: tuple[ForecastCashflow, ...] = (),
    history: tuple[str, ...] = (),
    interest_bearing: bool = False,
) -> ForecastInputSnapshot:
    periods = tuple(date(2025, month, 1) for month in range(10, 10 + len(history)))
    return ForecastInputSnapshot(
        owner_id=OWNER,
        captured_at=CAPTURED,
        as_of=date(2026, 1, 1),
        timezone="UTC",
        currency=RUB,
        accounts=(
            ForecastAccount(
                ACCOUNT,
                "Main",
                "savings" if interest_bearing else "bank",
                Money.of(balance, RUB),
                interest_bearing,
            ),
        ),
        scheduled_cashflows=cashflows,
        history_periods=periods,
        historical_expenses=tuple(
            HistoricalExpenseSample(period, ACCOUNT, Money.of(amount, RUB))
            for period, amount in zip(periods, history, strict=True)
        ),
    )


def _flow(
    event_id: str,
    occurs_on: date,
    amount: str,
    kind: ForecastFlowKind,
) -> ForecastCashflow:
    return ForecastCashflow(event_id, occurs_on, ACCOUNT, Money.of(amount, RUB), kind)


def _goal(
    goal_id: int,
    *,
    target: str,
    saved: str,
    target_date: date,
    priority: int = 1,
) -> FinancialGoal:
    return FinancialGoal(
        id=UUID(int=goal_id),
        owner_id=OWNER,
        name=f"Goal {goal_id}",
        target=Money.of(target, RUB),
        target_date=target_date,
        saved_amount=Money.of(saved, RUB),
        priority=priority,
    )


def test_zero_activity_golden() -> None:
    result = forecast_finances(
        _snapshot(),
        ForecastAssumptions(horizon=date(2026, 3, 31)),
    )

    assert len(result.timeline) == 3
    assert result.opening_total == Money.of("1000.00", RUB)
    assert result.final_total == Money.of("1000.00", RUB)
    assert result.uncertainty_low == result.final_total == result.uncertainty_high
    assert result.warnings == ("no_complete_history: irregular expense baseline is zero",)


def test_only_recurrence_golden() -> None:
    snapshot = _snapshot(
        cashflows=(
            _flow("salary-1", date(2026, 1, 15), "100.00", ForecastFlowKind.INCOME),
            _flow("rent-1", date(2026, 2, 1), "-20.00", ForecastFlowKind.EXPENSE),
        )
    )

    result = forecast_finances(
        snapshot,
        ForecastAssumptions(horizon=date(2026, 2, 28)),
    )

    assert result.timeline[0].scheduled_income == Money.of("100.00", RUB)
    assert result.timeline[1].scheduled_expense == Money.of("20.00", RUB)
    assert result.final_total == Money.of("1080.00", RUB)


def test_unmaterialized_same_day_recurrence_is_included() -> None:
    occurrence = Instant(datetime(2026, 1, 15, 8, tzinfo=UTC))
    rule = RecurringRule(
        id=UUID(int=20),
        owner_id=OWNER,
        operation=RecurringOperation(
            kind=TransactionKind.INCOME,
            account_id=ACCOUNT,
            category_id=SECOND_ACCOUNT,
            amount=Money.of("100.00", RUB),
        ),
        frequency=RecurrenceFrequency.MONTHLY,
        starts_on=date(2026, 1, 15),
        local_time=time(8),
        timezone="UTC",
        missing_day_policy=MissingDayPolicy.LAST_DAY,
        catch_up_policy=CatchUpPolicy.ALL,
        end_date=date(2026, 1, 15),
        next_occurrence_at=occurrence,
        status=RecurringRuleStatus.ACTIVE,
    )

    cashflows = _recurring_cashflows(
        (rule,),
        as_of=date(2026, 1, 15),
        through=date(2026, 1, 31),
        currency=RUB,
    )

    assert len(cashflows) == 1
    assert cashflows[0].occurs_on == date(2026, 1, 15)
    assert cashflows[0].amount == Money.of("100.00", RUB)


def test_deposit_maturity_interest_is_applied_on_schedule() -> None:
    result = forecast_finances(
        _snapshot(
            balance="10000.00",
            cashflows=(
                _flow(
                    "deposit:maturity",
                    date(2026, 3, 31),
                    "250.00",
                    ForecastFlowKind.DEPOSIT_INTEREST,
                ),
            ),
        ),
        ForecastAssumptions(horizon=date(2026, 3, 31)),
    )

    assert result.timeline[-1].deposit_interest == Money.of("250.00", RUB)
    assert result.final_total == Money.of("10250.00", RUB)


def test_inflation_uses_explicit_monthly_proration() -> None:
    result = forecast_finances(
        _snapshot(balance="1000.00", history=("120.00", "120.00", "120.00")),
        ForecastAssumptions(
            horizon=date(2026, 2, 28),
            annual_inflation=Rate.of("0.12"),
        ),
    )

    assert result.timeline[0].irregular_expense == Money.of("120.00", RUB)
    assert result.timeline[1].irregular_expense == Money.of("121.20", RUB)
    assert result.final_total == Money.of("758.80", RUB)


def test_scenario_is_pure_and_does_not_change_snapshot_or_other_result() -> None:
    snapshot = _snapshot(
        cashflows=(_flow("salary", date(2026, 1, 20), "100.00", ForecastFlowKind.INCOME),)
    )
    baseline_assumptions = ForecastAssumptions(horizon=date(2026, 1, 31))
    baseline = forecast_finances(snapshot, baseline_assumptions)
    scenario = forecast_finances(
        snapshot,
        ForecastAssumptions(
            horizon=date(2026, 1, 31),
            income_change=Rate.of("0.50"),
            one_time_cashflows=(
                OneTimeCashflow(date(2026, 1, 25), ACCOUNT, Money.of("-10.00", RUB)),
            ),
        ),
    )

    assert scenario.final_total == Money.of("1140.00", RUB)
    assert forecast_finances(snapshot, baseline_assumptions) == baseline
    assert snapshot.accounts[0].opening_balance == Money.of("1000.00", RUB)


def test_goal_missed_already_achieved_and_impossible_are_numeric() -> None:
    forecast = forecast_finances(
        _snapshot(balance="0.00"),
        ForecastAssumptions(horizon=date(2026, 2, 28)),
    )
    result = plan_goals(
        forecast,
        (
            _goal(1, target="100.00", saved="0.00", target_date=date(2025, 12, 31)),
            _goal(2, target="100.00", saved="100.00", target_date=date(2026, 2, 28)),
            _goal(3, target="100.00", saved="0.00", target_date=date(2026, 2, 28)),
        ),
    )
    missed, achieved, impossible = result.goals

    assert missed.status == "missed_target"
    assert missed.required_monthly_contribution == Money.of("100.00", RUB)
    assert missed.shortfall == Money.of("100.00", RUB)
    assert achieved.status == "already_achieved"
    assert achieved.required_monthly_contribution == Money.of("0.00", RUB)
    assert achieved.expected_completion_date == date(2026, 1, 1)
    assert impossible.status == "shortfall"
    assert impossible.required_monthly_contribution == Money.of("50.00", RUB)
    assert impossible.contribution_gap == Money.of("50.00", RUB)
    assert impossible.shortfall == Money.of("100.00", RUB)


def test_multiple_goals_use_priority_waterfall() -> None:
    forecast = forecast_finances(
        _snapshot(
            balance="0.00",
            cashflows=(
                _flow("income-1", date(2026, 1, 20), "100.00", ForecastFlowKind.INCOME),
                _flow("income-2", date(2026, 2, 20), "100.00", ForecastFlowKind.INCOME),
                _flow("income-3", date(2026, 3, 20), "100.00", ForecastFlowKind.INCOME),
            ),
        ),
        ForecastAssumptions(horizon=date(2026, 3, 31)),
    )
    result = plan_goals(
        forecast,
        (
            _goal(10, target="100.00", saved="0.00", target_date=date(2026, 3, 31), priority=2),
            _goal(11, target="150.00", saved="0.00", target_date=date(2026, 3, 31), priority=1),
        ),
    )
    high, low = result.goals

    assert high.goal_id == UUID(int=11)
    assert high.allocated_through_target == Money.of("150.00", RUB)
    assert high.expected_completion_date == date(2026, 2, 28)
    assert low.allocated_through_target == Money.of("100.00", RUB)
    assert low.expected_completion_date == date(2026, 3, 31)


@given(
    balance=st.integers(min_value=-100000, max_value=100000),
    annual_basis_points=st.integers(min_value=0, max_value=5000),
)
def test_same_snapshot_and_algorithm_are_reproducible(
    balance: int, annual_basis_points: int
) -> None:
    snapshot = _snapshot(
        balance=f"{balance}.00",
        history=("10.00", "20.00", "30.00"),
        interest_bearing=True,
    )
    assumptions = ForecastAssumptions(
        horizon=date(2026, 12, 31),
        annual_interest=Rate.of(Decimal(annual_basis_points) / Decimal("10000")),
    )

    first = forecast_finances(snapshot, assumptions)
    second = forecast_finances(snapshot, assumptions)

    assert first == second
    assert first.snapshot_id == snapshot.snapshot_id
