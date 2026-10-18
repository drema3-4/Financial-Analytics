from __future__ import annotations

import calendar
import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal, localcontext
from enum import StrEnum
from statistics import median
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from financial_analytics_domain.errors import DomainError
from financial_analytics_domain.values import Currency, Instant, Money, Rate, RoundingPolicy

FORECAST_ALGORITHM_VERSION = "monthly-cashflow-v1"
FORECAST_ASSUMPTIONS_VERSION = "forecast-assumptions-v1"
UNCERTAINTY_METHOD_VERSION = "historical-expense-min-max-v1"
GOAL_ALLOCATION_VERSION = "priority-waterfall-v1"
MINIMUM_HISTORY_MONTHS = 3
MAXIMUM_FORECAST_MONTHS = 600


class ForecastFlowKind(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"
    TRANSFER = "transfer"
    DEPOSIT_INTEREST = "deposit_interest"


@dataclass(frozen=True, slots=True)
class ForecastAccount:
    id: UUID
    name: str
    kind: str
    opening_balance: Money
    interest_bearing: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise DomainError("forecast account name must not be empty")


@dataclass(frozen=True, slots=True)
class ForecastCashflow:
    event_id: str
    occurs_on: date
    account_id: UUID
    amount: Money
    kind: ForecastFlowKind

    def __post_init__(self) -> None:
        if not self.event_id:
            raise DomainError("forecast cashflow event_id must not be empty")
        if self.amount.amount == 0:
            raise DomainError("forecast cashflow must not be zero")
        if (
            self.kind in {ForecastFlowKind.INCOME, ForecastFlowKind.DEPOSIT_INTEREST}
            and self.amount.amount <= 0
        ):
            raise DomainError("forecast income must be positive")
        if self.kind is ForecastFlowKind.EXPENSE and self.amount.amount >= 0:
            raise DomainError("forecast expense must be negative")


@dataclass(frozen=True, slots=True)
class HistoricalExpenseSample:
    period_start: date
    account_id: UUID
    amount: Money

    def __post_init__(self) -> None:
        if self.period_start.day != 1:
            raise DomainError("historical expense periods must start on day one")
        if self.amount.amount < 0:
            raise DomainError("historical expense sample must not be negative")


@dataclass(frozen=True, slots=True)
class OneTimeCashflow:
    occurs_on: date
    account_id: UUID
    amount: Money
    description: str = ""

    def __post_init__(self) -> None:
        if self.amount.amount == 0:
            raise DomainError("one-time cashflow must not be zero")
        if len(self.description) > 500:
            raise DomainError("one-time cashflow description is too long")


@dataclass(frozen=True, slots=True)
class ForecastAssumptions:
    horizon: date
    income_change: Rate = Rate(Decimal("0"))
    expense_change: Rate = Rate(Decimal("0"))
    annual_inflation: Rate = Rate(Decimal("0"))
    annual_interest: Rate = Rate(Decimal("0"))
    one_time_cashflows: tuple[OneTimeCashflow, ...] = ()
    version: str = FORECAST_ASSUMPTIONS_VERSION

    def __post_init__(self) -> None:
        if self.version != FORECAST_ASSUMPTIONS_VERSION:
            raise DomainError("unsupported forecast assumptions version")
        if self.income_change.value < -1 or self.expense_change.value < -1:
            raise DomainError("income and expense changes cannot be below -100%")
        if self.annual_inflation.value < 0 or self.annual_interest.value < 0:
            raise DomainError("inflation and interest rates must not be negative")


@dataclass(frozen=True, slots=True)
class ForecastScenario:
    id: UUID
    owner_id: UUID
    name: str
    currency: Currency
    assumptions: ForecastAssumptions
    version: int = 1

    def __post_init__(self) -> None:
        if not self.name.strip() or len(self.name) > 160:
            raise DomainError("scenario name must contain 1 to 160 characters")
        if self.version < 1:
            raise DomainError("scenario version must be positive")
        if any(
            item.amount.currency != self.currency for item in self.assumptions.one_time_cashflows
        ):
            raise DomainError("scenario cashflows must use the scenario currency")


@dataclass(frozen=True, slots=True)
class ForecastInputSnapshot:
    owner_id: UUID
    captured_at: Instant
    as_of: date
    timezone: str
    currency: Currency
    accounts: tuple[ForecastAccount, ...]
    scheduled_cashflows: tuple[ForecastCashflow, ...]
    history_periods: tuple[date, ...]
    historical_expenses: tuple[HistoricalExpenseSample, ...]

    def __post_init__(self) -> None:
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise DomainError("forecast timezone must be an IANA timezone") from error
        if self.captured_at.value.astimezone(ZoneInfo(self.timezone)).date() != self.as_of:
            raise DomainError("forecast as_of must match captured_at in the user timezone")
        account_ids = [item.id for item in self.accounts]
        if len(account_ids) != len(set(account_ids)):
            raise DomainError("forecast accounts must be unique")
        if any(item.opening_balance.currency != self.currency for item in self.accounts):
            raise DomainError("forecast accounts must use the snapshot currency")
        known = set(account_ids)
        referenced = tuple(
            (item.account_id, item.amount.currency) for item in self.scheduled_cashflows
        ) + tuple((item.account_id, item.amount.currency) for item in self.historical_expenses)
        for account_id, currency in referenced:
            if account_id not in known or currency != self.currency:
                raise DomainError("forecast input references an unknown account or currency")
        if len(self.history_periods) != len(set(self.history_periods)):
            raise DomainError("forecast history periods must be unique")
        if any(item.day != 1 for item in self.history_periods):
            raise DomainError("forecast history periods must be complete calendar months")

    @property
    def snapshot_id(self) -> str:
        payload = {
            "owner_id": str(self.owner_id),
            "captured_at": self.captured_at.value.isoformat(),
            "as_of": self.as_of.isoformat(),
            "timezone": self.timezone,
            "currency": self.currency.code,
            "accounts": [
                {
                    "id": str(item.id),
                    "name": item.name,
                    "kind": item.kind,
                    "balance": _decimal_text(item.opening_balance.amount),
                    "interest_bearing": item.interest_bearing,
                }
                for item in sorted(self.accounts, key=lambda value: str(value.id))
            ],
            "scheduled_cashflows": [
                {
                    "event_id": item.event_id,
                    "occurs_on": item.occurs_on.isoformat(),
                    "account_id": str(item.account_id),
                    "amount": _decimal_text(item.amount.amount),
                    "kind": item.kind.value,
                }
                for item in sorted(
                    self.scheduled_cashflows,
                    key=lambda value: (
                        value.occurs_on,
                        value.event_id,
                        str(value.account_id),
                    ),
                )
            ],
            "history_periods": [item.isoformat() for item in sorted(self.history_periods)],
            "historical_expenses": [
                {
                    "period_start": item.period_start.isoformat(),
                    "account_id": str(item.account_id),
                    "amount": _decimal_text(item.amount.amount),
                }
                for item in sorted(
                    self.historical_expenses,
                    key=lambda value: (value.period_start, str(value.account_id)),
                )
            ],
        }
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class BaselineExpense:
    account_id: UUID
    monthly_median: Money
    observed_minimum: Money
    observed_maximum: Money
    sample_count: int


@dataclass(frozen=True, slots=True)
class AccountForecast:
    account_id: UUID
    name: str
    opening_balance: Money
    closing_balance: Money


@dataclass(frozen=True, slots=True)
class ForecastMonth:
    starts_on: date
    ends_on: date
    opening_total: Money
    scheduled_income: Money
    scheduled_expense: Money
    irregular_expense: Money
    deposit_interest: Money
    savings_interest: Money
    one_time_net: Money
    net_change: Money
    closing_total: Money
    uncertainty_low: Money
    uncertainty_high: Money
    accounts: tuple[AccountForecast, ...]


@dataclass(frozen=True, slots=True)
class ForecastResult:
    snapshot_id: str
    algorithm_version: str
    assumptions: ForecastAssumptions
    uncertainty_method: str
    uncertainty_explanation: str
    baseline_expenses: tuple[BaselineExpense, ...]
    warnings: tuple[str, ...]
    timeline: tuple[ForecastMonth, ...]
    accounts: tuple[AccountForecast, ...]
    opening_total: Money
    final_total: Money
    uncertainty_low: Money
    uncertainty_high: Money


@dataclass(frozen=True, slots=True)
class FinancialGoal:
    id: UUID
    owner_id: UUID
    name: str
    target: Money
    target_date: date
    saved_amount: Money
    priority: int
    linked_account_id: UUID | None = None
    version: int = 1
    archived: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip() or len(self.name) > 160:
            raise DomainError("goal name must contain 1 to 160 characters")
        if self.target.amount <= 0:
            raise DomainError("goal target must be positive")
        if self.saved_amount.amount < 0:
            raise DomainError("goal saved amount must not be negative")
        if self.saved_amount.currency != self.target.currency:
            raise DomainError("goal target and saved amount currencies must match")
        if self.priority < 1:
            raise DomainError("goal priority must be positive")
        if self.version < 1:
            raise DomainError("goal version must be positive")


@dataclass(frozen=True, slots=True)
class GoalPlan:
    goal_id: UUID
    name: str
    priority: int
    linked_account_id: UUID | None
    target: Money
    target_date: date
    saved_amount: Money
    remaining_amount: Money
    required_monthly_contribution: Money
    average_available_monthly: Money
    contribution_gap: Money
    allocated_through_target: Money
    projected_saved_at_target: Money
    expected_completion_date: date | None
    shortfall: Money
    feasible_by_target: bool
    status: str


@dataclass(frozen=True, slots=True)
class GoalPlanResult:
    allocation_version: str
    allocation_explanation: str
    forecast_snapshot_id: str
    currency: Currency
    warnings: tuple[str, ...]
    goals: tuple[GoalPlan, ...]


def forecast_finances(
    snapshot: ForecastInputSnapshot,
    assumptions: ForecastAssumptions,
    *,
    algorithm_version: str = FORECAST_ALGORITHM_VERSION,
) -> ForecastResult:
    """Build a pure, deterministic monthly forecast from one immutable snapshot."""

    if algorithm_version != FORECAST_ALGORITHM_VERSION:
        raise DomainError("unsupported forecast algorithm version")
    if assumptions.horizon < snapshot.as_of:
        raise DomainError("forecast horizon must not precede as_of")
    slices = _month_slices(snapshot.as_of, assumptions.horizon)
    if len(slices) > MAXIMUM_FORECAST_MONTHS:
        raise DomainError("forecast horizon exceeds 600 months")
    account_map = {item.id: item for item in snapshot.accounts}
    for item in assumptions.one_time_cashflows:
        if item.account_id not in account_map or item.amount.currency != snapshot.currency:
            raise DomainError("one-time cashflow references an unknown account or currency")
        if not snapshot.as_of <= item.occurs_on <= assumptions.horizon:
            raise DomainError("one-time cashflow must fall within the forecast horizon")

    baseline = _baseline_expenses(snapshot)
    baseline_map = {item.account_id: item for item in baseline}
    states = {
        "baseline": {item.id: item.opening_balance.amount for item in snapshot.accounts},
        "low": {item.id: item.opening_balance.amount for item in snapshot.accounts},
        "high": {item.id: item.opening_balance.amount for item in snapshot.accounts},
    }
    opening_total_value = sum(states["baseline"].values(), start=Decimal("0"))
    timeline: list[ForecastMonth] = []
    warnings: list[str] = []
    if not snapshot.history_periods:
        warnings.append("no_complete_history: irregular expense baseline is zero")
    elif len(snapshot.history_periods) < MINIMUM_HISTORY_MONTHS:
        warnings.append(
            "insufficient_history: fewer than 3 complete months; baseline and range are unstable"
        )

    scheduled = tuple(
        item
        for item in snapshot.scheduled_cashflows
        if snapshot.as_of <= item.occurs_on <= assumptions.horizon
    )
    for month_index, (starts_on, ends_on) in enumerate(slices):
        opening = dict(states["baseline"])
        opening_total = sum(opening.values(), start=Decimal("0"))
        inflation_factor = _inflation_factor(assumptions.annual_inflation.value, month_index)
        scheduled_income = Decimal("0")
        scheduled_expense = Decimal("0")
        deposit_interest = Decimal("0")
        one_time_net = Decimal("0")

        for scheduled_item in scheduled:
            if not starts_on <= scheduled_item.occurs_on < ends_on:
                continue
            amount = _adjust_scheduled(scheduled_item, assumptions, inflation_factor)
            for state in states.values():
                state[scheduled_item.account_id] += amount
            if scheduled_item.kind is ForecastFlowKind.INCOME:
                scheduled_income += amount
            elif scheduled_item.kind is ForecastFlowKind.EXPENSE:
                scheduled_expense += -amount
            elif scheduled_item.kind is ForecastFlowKind.DEPOSIT_INTEREST:
                deposit_interest += amount

        for one_time in assumptions.one_time_cashflows:
            if starts_on <= one_time.occurs_on < ends_on:
                for state in states.values():
                    state[one_time.account_id] += one_time.amount.amount
                one_time_net += one_time.amount.amount

        days = Decimal((ends_on - starts_on).days)
        month_days = Decimal(calendar.monthrange(starts_on.year, starts_on.month)[1])
        irregular_baseline = Decimal("0")
        for account_id in account_map:
            estimate = baseline_map[account_id]
            variants = {
                "baseline": estimate.monthly_median.amount,
                "low": estimate.observed_minimum.amount,
                "high": estimate.observed_maximum.amount,
            }
            for variant, monthly in variants.items():
                exact = (
                    monthly
                    * (Decimal("1") + assumptions.expense_change.value)
                    * inflation_factor
                    * days
                    / month_days
                )
                expense = _round(exact, snapshot.currency)
                states[variant][account_id] -= expense
                if variant == "baseline":
                    irregular_baseline += expense

        interest_by_variant: dict[str, Decimal] = {}
        for variant, state in states.items():
            interest_total = Decimal("0")
            for account_id, account in account_map.items():
                if not account.interest_bearing or state[account_id] <= 0:
                    continue
                exact_interest = (
                    state[account_id]
                    * assumptions.annual_interest.value
                    / Decimal("12")
                    * days
                    / month_days
                )
                interest = _round(exact_interest, snapshot.currency)
                state[account_id] += interest
                interest_total += interest
            interest_by_variant[variant] = interest_total

        closing_total = sum(states["baseline"].values(), start=Decimal("0"))
        low_total = sum(states["high"].values(), start=Decimal("0"))
        high_total = sum(states["low"].values(), start=Decimal("0"))
        if any(value < 0 for value in states["baseline"].values()):
            marker = f"negative_account_balance:{starts_on.isoformat()}"
            if marker not in warnings:
                warnings.append(marker)
        account_rows = tuple(
            AccountForecast(
                account_id=item.id,
                name=item.name,
                opening_balance=Money.of(opening[item.id], snapshot.currency),
                closing_balance=Money.of(states["baseline"][item.id], snapshot.currency),
            )
            for item in sorted(snapshot.accounts, key=lambda value: (value.name, str(value.id)))
        )
        timeline.append(
            ForecastMonth(
                starts_on=starts_on,
                ends_on=ends_on,
                opening_total=Money.of(opening_total, snapshot.currency),
                scheduled_income=Money.of(scheduled_income, snapshot.currency),
                scheduled_expense=Money.of(scheduled_expense, snapshot.currency),
                irregular_expense=Money.of(irregular_baseline, snapshot.currency),
                deposit_interest=Money.of(deposit_interest, snapshot.currency),
                savings_interest=Money.of(interest_by_variant["baseline"], snapshot.currency),
                one_time_net=Money.of(one_time_net, snapshot.currency),
                net_change=Money.of(closing_total - opening_total, snapshot.currency),
                closing_total=Money.of(closing_total, snapshot.currency),
                uncertainty_low=Money.of(low_total, snapshot.currency),
                uncertainty_high=Money.of(high_total, snapshot.currency),
                accounts=account_rows,
            )
        )

    final_accounts = tuple(
        AccountForecast(
            account_id=item.id,
            name=item.name,
            opening_balance=item.opening_balance,
            closing_balance=Money.of(states["baseline"][item.id], snapshot.currency),
        )
        for item in sorted(snapshot.accounts, key=lambda value: (value.name, str(value.id)))
    )
    final_total = sum(states["baseline"].values(), start=Decimal("0"))
    low_total = sum(states["high"].values(), start=Decimal("0"))
    high_total = sum(states["low"].values(), start=Decimal("0"))
    return ForecastResult(
        snapshot_id=snapshot.snapshot_id,
        algorithm_version=algorithm_version,
        assumptions=assumptions,
        uncertainty_method=UNCERTAINTY_METHOD_VERSION,
        uncertainty_explanation=(
            "All scheduled cashflows are fixed. Irregular expenses use the median of complete "
            "historical months; the low/high capital bounds substitute the observed monthly "
            "maximum/minimum respectively and compound the same explicit savings interest."
        ),
        baseline_expenses=baseline,
        warnings=tuple(warnings),
        timeline=tuple(timeline),
        accounts=final_accounts,
        opening_total=Money.of(opening_total_value, snapshot.currency),
        final_total=Money.of(final_total, snapshot.currency),
        uncertainty_low=Money.of(low_total, snapshot.currency),
        uncertainty_high=Money.of(high_total, snapshot.currency),
    )


def plan_goals(
    forecast: ForecastResult,
    goals: tuple[FinancialGoal, ...],
) -> GoalPlanResult:
    """Allocate positive monthly forecast cashflow by explicit priority waterfall."""

    currency = forecast.final_total.currency
    selected = tuple(goal for goal in goals if goal.target.currency == currency)
    ordered = tuple(
        sorted(selected, key=lambda item: (item.priority, item.target_date, str(item.id)))
    )
    remaining = {
        item.id: max(item.target.amount - item.saved_amount.amount, Decimal("0"))
        for item in ordered
    }
    allocations: dict[UUID, list[tuple[date, Decimal]]] = {item.id: [] for item in ordered}
    for row in forecast.timeline:
        available = max(row.net_change.amount, Decimal("0"))
        allocation_date = row.ends_on - timedelta(days=1)
        for goal in ordered:
            if available <= 0:
                break
            contribution = min(available, remaining[goal.id])
            if contribution > 0:
                allocations[goal.id].append((allocation_date, contribution))
                remaining[goal.id] -= contribution
                available -= contribution

    plans: list[GoalPlan] = []
    warnings: list[str] = []
    as_of = forecast.timeline[0].starts_on if forecast.timeline else forecast.assumptions.horizon
    for goal in ordered:
        initial_remaining = max(goal.target.amount - goal.saved_amount.amount, Decimal("0"))
        opportunity_count = _contribution_months(as_of, goal.target_date)
        required = _ceil_money(
            (
                initial_remaining / Decimal(opportunity_count)
                if opportunity_count
                else initial_remaining
            ),
            currency,
        )
        eligible_rows = [
            row for row in forecast.timeline if row.ends_on - timedelta(days=1) <= goal.target_date
        ]
        available_total = sum(
            (max(row.net_change.amount, Decimal("0")) for row in eligible_rows),
            start=Decimal("0"),
        )
        average_available = _round(
            available_total / Decimal(len(eligible_rows)) if eligible_rows else Decimal("0"),
            currency,
        )
        through_target = sum(
            (
                amount
                for allocated_on, amount in allocations[goal.id]
                if allocated_on <= goal.target_date
            ),
            start=Decimal("0"),
        )
        projected = min(goal.target.amount, goal.saved_amount.amount + through_target)
        shortfall = max(goal.target.amount - projected, Decimal("0"))
        expected = as_of if initial_remaining == 0 else None
        running = Decimal("0")
        for allocated_on, amount in allocations[goal.id]:
            running += amount
            if running >= initial_remaining:
                expected = allocated_on
                break
        status = "already_achieved" if initial_remaining == 0 else "on_track"
        if goal.target_date < as_of and initial_remaining > 0:
            status = "missed_target"
        elif shortfall > 0:
            status = "shortfall"
        if goal.target_date > forecast.assumptions.horizon:
            warnings.append(f"horizon_before_target:{goal.id}")
        gap = max(required - average_available, Decimal("0"))
        plans.append(
            GoalPlan(
                goal_id=goal.id,
                name=goal.name,
                priority=goal.priority,
                linked_account_id=goal.linked_account_id,
                target=goal.target,
                target_date=goal.target_date,
                saved_amount=goal.saved_amount,
                remaining_amount=Money.of(initial_remaining, currency),
                required_monthly_contribution=Money.of(required, currency),
                average_available_monthly=Money.of(average_available, currency),
                contribution_gap=Money.of(gap, currency),
                allocated_through_target=Money.of(through_target, currency),
                projected_saved_at_target=Money.of(projected, currency),
                expected_completion_date=expected,
                shortfall=Money.of(shortfall, currency),
                feasible_by_target=shortfall == 0,
                status=status,
            )
        )
    return GoalPlanResult(
        allocation_version=GOAL_ALLOCATION_VERSION,
        allocation_explanation=(
            "At each month end, positive projected net cashflow is assigned in ascending "
            "priority number, then target date and goal UUID; each goal is capped at its "
            "remaining target. No optimizer or LLM is used."
        ),
        forecast_snapshot_id=forecast.snapshot_id,
        currency=currency,
        warnings=tuple(warnings),
        goals=tuple(plans),
    )


def _baseline_expenses(snapshot: ForecastInputSnapshot) -> tuple[BaselineExpense, ...]:
    samples = {
        (item.period_start, item.account_id): item.amount.amount
        for item in snapshot.historical_expenses
    }
    result: list[BaselineExpense] = []
    for account in sorted(snapshot.accounts, key=lambda item: str(item.id)):
        values = [
            samples.get((period, account.id), Decimal("0")) for period in snapshot.history_periods
        ]
        if values:
            center = Decimal(median(values))
            minimum = min(values)
            maximum = max(values)
        else:
            center = minimum = maximum = Decimal("0")
        result.append(
            BaselineExpense(
                account_id=account.id,
                monthly_median=Money.of(center, snapshot.currency),
                observed_minimum=Money.of(minimum, snapshot.currency),
                observed_maximum=Money.of(maximum, snapshot.currency),
                sample_count=len(values),
            )
        )
    return tuple(result)


def _month_slices(as_of: date, horizon: date) -> tuple[tuple[date, date], ...]:
    result: list[tuple[date, date]] = []
    cursor = as_of
    final = horizon + timedelta(days=1)
    while cursor < final:
        if cursor.month == 12:
            next_month = date(cursor.year + 1, 1, 1)
        else:
            next_month = date(cursor.year, cursor.month + 1, 1)
        end = min(next_month, final)
        result.append((cursor, end))
        cursor = end
    return tuple(result)


def _adjust_scheduled(
    item: ForecastCashflow,
    assumptions: ForecastAssumptions,
    inflation_factor: Decimal,
) -> Decimal:
    multiplier = Decimal("1")
    if item.kind is ForecastFlowKind.INCOME:
        multiplier += assumptions.income_change.value
    elif item.kind is ForecastFlowKind.EXPENSE:
        multiplier = (multiplier + assumptions.expense_change.value) * inflation_factor
    return _round(item.amount.amount * multiplier, item.amount.currency)


def _inflation_factor(annual_rate: Decimal, month_index: int) -> Decimal:
    with localcontext() as context:
        context.prec = 64
        return (Decimal("1") + annual_rate / Decimal("12")) ** month_index


def _round(value: Decimal, currency: Currency) -> Decimal:
    return RoundingPolicy.HALF_EVEN.round(value, currency)


def _ceil_money(value: Decimal, currency: Currency) -> Decimal:
    with localcontext() as context:
        context.prec = 64
        return value.quantize(currency.quantum, rounding=ROUND_CEILING)


def _contribution_months(as_of: date, target: date) -> int:
    if target < as_of:
        return 0
    return (target.year - as_of.year) * 12 + target.month - as_of.month + 1


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")
