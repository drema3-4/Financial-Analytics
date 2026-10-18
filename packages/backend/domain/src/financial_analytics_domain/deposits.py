from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal, localcontext
from enum import StrEnum
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from financial_analytics_domain.errors import DomainError
from financial_analytics_domain.values import Currency, Instant, Money, Rate, RoundingPolicy

DEPOSIT_ALGORITHM_VERSION = "deposit-interest-v1"
_ZERO = Decimal(0)
_ONE = Decimal(1)


class CapitalizationFrequency(StrEnum):
    DAILY = "daily"
    MONTHLY_CALENDAR_END = "monthly_calendar_end"


class DayCountConvention(StrEnum):
    ACTUAL_365_FIXED = "actual_365_fixed"
    ACTUAL_ACTUAL_ISDA = "actual_actual_isda"


class InterestRoundingFrequency(StrEnum):
    DAILY = "daily"
    CAPITALIZATION = "capitalization"


class EarlyClosePolicy(StrEnum):
    FORBID = "forbid"
    FORFEIT_INTEREST = "forfeit_interest"
    REPRICE = "reprice"


@dataclass(frozen=True, slots=True)
class DepositRatePeriod:
    starts_on: date
    ends_on: date
    nominal_rate: Rate

    def __post_init__(self) -> None:
        if isinstance(self.starts_on, datetime) or isinstance(self.ends_on, datetime):
            raise TypeError("rate period boundaries must be dates")
        if self.starts_on >= self.ends_on:
            raise DomainError("rate period end must be after start")
        if self.nominal_rate.value < 0:
            raise DomainError("deposit nominal rate must not be negative")


@dataclass(frozen=True, slots=True)
class EarlyCloseRule:
    policy: EarlyClosePolicy
    nominal_rate: Rate | None

    def __post_init__(self) -> None:
        if (self.policy is EarlyClosePolicy.REPRICE) != (self.nominal_rate is not None):
            raise DomainError("reprice early-close policy requires exactly one nominal rate")
        if self.nominal_rate is not None and self.nominal_rate.value < 0:
            raise DomainError("early-close nominal rate must not be negative")


@dataclass(frozen=True, slots=True)
class DepositTerms:
    id: UUID
    owner_id: UUID
    principal_account_id: UUID
    currency: Currency
    opened_on: date
    matures_on: date
    rate_periods: tuple[DepositRatePeriod, ...]
    capitalization_frequency: CapitalizationFrequency
    day_count_convention: DayCountConvention
    rounding_policy: RoundingPolicy
    interest_rounding_frequency: InterestRoundingFrequency
    timezone: str
    cashflow_cutoff_time: time
    cashflow_cutoff_inclusive: bool
    early_close_rule: EarlyCloseRule
    tax_rate: Rate
    algorithm_version: str = DEPOSIT_ALGORITHM_VERSION
    name: str = "Вклад"
    archived: bool = False
    version: int = 1
    automatic_interest: bool = True

    def __post_init__(self) -> None:
        if isinstance(self.opened_on, datetime) or isinstance(self.matures_on, datetime):
            raise TypeError("deposit boundaries must be dates")
        if self.opened_on >= self.matures_on:
            raise DomainError("deposit maturity must be after opening")
        if not self.rate_periods:
            raise DomainError("deposit requires at least one rate period")
        ordered = tuple(sorted(self.rate_periods, key=lambda period: period.starts_on))
        if ordered != self.rate_periods:
            raise DomainError("deposit rate periods must be ordered")
        expected_start = self.opened_on
        for period in ordered:
            if period.starts_on != expected_start:
                raise DomainError("deposit rate periods must cover the term without gaps")
            expected_start = period.ends_on
        if expected_start != self.matures_on:
            raise DomainError("deposit rate periods must end at maturity")
        if not (_ZERO <= self.tax_rate.value < _ONE):
            raise DomainError("deposit tax rate must be in [0, 1)")
        if self.cashflow_cutoff_time.tzinfo is not None:
            raise DomainError("deposit cashflow cut-off must be a local wall-clock time")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise DomainError("deposit timezone must be a valid IANA timezone") from error
        if self.algorithm_version != DEPOSIT_ALGORITHM_VERSION:
            raise DomainError("unsupported deposit interest algorithm version")
        if not self.name.strip() or len(self.name) > 160:
            raise DomainError("deposit name must contain 1 to 160 characters")
        if self.version < 1:
            raise DomainError("deposit version must be positive")


@dataclass(frozen=True, slots=True)
class DepositCashflow:
    transaction_id: UUID
    occurred_at: Instant
    amount: Money

    def __post_init__(self) -> None:
        if self.amount.amount == 0:
            raise DomainError("deposit cashflow must not be zero")


@dataclass(frozen=True, slots=True)
class InterestScheduleEntry:
    accrual_starts_on: date
    accrual_ends_on: date
    posting_date: date
    opening_balance: Money
    cashflow: Money
    gross_interest: Money
    tax: Money
    net_interest: Money
    closing_balance: Money


@dataclass(frozen=True, slots=True)
class DepositProjection:
    algorithm_version: str
    as_of: date
    closes_on: date
    schedule: tuple[InterestScheduleEntry, ...]
    current_principal: Money
    accrued_interest: Money
    current_value: Money
    projected_closing_value: Money
    effective_yield: Rate | None


@dataclass(frozen=True, slots=True)
class _Simulation:
    entries: tuple[InterestScheduleEntry, ...]
    balance: Decimal
    pending_interest: Decimal


def effective_cashflow_date(terms: DepositTerms, cashflow: DepositCashflow) -> date:
    """Map an instant to the explicit local banking cut-off convention."""

    if cashflow.amount.currency != terms.currency:
        raise DomainError("deposit cashflow currency differs from terms")
    local = cashflow.occurred_at.value.astimezone(ZoneInfo(terms.timezone))
    before = local.timetz().replace(tzinfo=None) < terms.cashflow_cutoff_time
    exactly = local.timetz().replace(tzinfo=None) == terms.cashflow_cutoff_time
    if before or (exactly and terms.cashflow_cutoff_inclusive):
        return local.date()
    return local.date() + timedelta(days=1)


def day_count_fraction(
    starts_on: date,
    ends_on: date,
    convention: DayCountConvention,
) -> Decimal:
    """Return an exact year fraction for a half-open date interval."""

    if starts_on > ends_on:
        raise DomainError("day-count end must not precede start")
    if starts_on == ends_on:
        return _ZERO
    if convention is DayCountConvention.ACTUAL_365_FIXED:
        return Decimal((ends_on - starts_on).days) / Decimal(365)
    cursor = starts_on
    result = _ZERO
    with localcontext() as context:
        context.prec = 64
        while cursor < ends_on:
            boundary = min(ends_on, date(cursor.year + 1, 1, 1))
            denominator = Decimal(366 if _is_leap_year(cursor.year) else 365)
            result += Decimal((boundary - cursor).days) / denominator
            cursor = boundary
    return result


def project_deposit(
    terms: DepositTerms,
    cashflows: tuple[DepositCashflow, ...],
    *,
    as_of: date,
    close_on: date | None = None,
) -> DepositProjection:
    """Pure deterministic interest projection; no clock, persistence, or framework access."""

    closes_on, applied_terms = _terms_for_close(terms, close_on)
    if not terms.opened_on <= as_of <= closes_on:
        raise DomainError("deposit valuation date must be within its evaluated term")
    effective = _effective_cashflows(applied_terms, cashflows, closes_on)
    full = _simulate(applied_terms, effective, closes_on, settle_at_end=True)
    current = _simulate(applied_terms, effective, as_of, settle_at_end=False)
    accrued = _net_pending(applied_terms, current.pending_interest)
    current_principal = _money(current.balance, terms)
    accrued_money = _money(accrued, terms)
    projected = _money(full.balance + _net_pending(applied_terms, full.pending_interest), terms)
    return DepositProjection(
        algorithm_version=terms.algorithm_version,
        as_of=as_of,
        closes_on=closes_on,
        schedule=full.entries,
        current_principal=current_principal,
        accrued_interest=accrued_money,
        current_value=_money(current_principal.amount + accrued_money.amount, terms),
        projected_closing_value=projected,
        effective_yield=_effective_yield(applied_terms, effective, closes_on, projected.amount),
    )


def _terms_for_close(terms: DepositTerms, close_on: date | None) -> tuple[date, DepositTerms]:
    if close_on is None or close_on == terms.matures_on:
        return terms.matures_on, terms
    if not terms.opened_on < close_on < terms.matures_on:
        raise DomainError("early-close date must be after opening and before maturity")
    rule = terms.early_close_rule
    if rule.policy is EarlyClosePolicy.FORBID:
        raise DomainError("deposit terms forbid early close")
    nominal = (
        Rate.of("0") if rule.policy is EarlyClosePolicy.FORFEIT_INTEREST else rule.nominal_rate
    )
    assert nominal is not None
    return close_on, replace(
        terms,
        matures_on=close_on,
        rate_periods=(DepositRatePeriod(terms.opened_on, close_on, nominal),),
    )


def _effective_cashflows(
    terms: DepositTerms,
    cashflows: tuple[DepositCashflow, ...],
    closes_on: date,
) -> tuple[tuple[date, DepositCashflow], ...]:
    result: list[tuple[date, DepositCashflow]] = []
    for cashflow in cashflows:
        effective_on = effective_cashflow_date(terms, cashflow)
        if not terms.opened_on <= effective_on < closes_on:
            raise DomainError("deposit cashflow effective date is outside the evaluated term")
        result.append((effective_on, cashflow))
    return tuple(
        sorted(
            result,
            key=lambda item: (item[0], item[1].occurred_at.value, item[1].transaction_id),
        )
    )


def _simulate(
    terms: DepositTerms,
    cashflows: tuple[tuple[date, DepositCashflow], ...],
    ends_on: date,
    *,
    settle_at_end: bool,
) -> _Simulation:
    flows_by_date: defaultdict[date, list[DepositCashflow]] = defaultdict(list)
    for effective_on, cashflow in cashflows:
        if effective_on < ends_on:
            flows_by_date[effective_on].append(cashflow)

    balance = _ZERO
    pending = _ZERO
    period_opening = _ZERO
    period_cashflow = _ZERO
    period_start = terms.opened_on
    entries: list[InterestScheduleEntry] = []
    current = terms.opened_on
    with localcontext() as context:
        context.prec = 64
        while current < ends_on:
            for cashflow in flows_by_date[current]:
                balance += cashflow.amount.amount
                period_cashflow += cashflow.amount.amount
                if balance < 0:
                    raise DomainError("deposit withdrawal exceeds the projected balance")
            next_date = current + timedelta(days=1)
            rate = _rate_on(terms, current)
            exact_interest = (
                balance
                * rate.value
                * day_count_fraction(current, next_date, terms.day_count_convention)
            )
            if terms.interest_rounding_frequency is InterestRoundingFrequency.DAILY:
                exact_interest = _rounded(exact_interest, terms)
            pending += exact_interest
            capitalizes = (
                terms.capitalization_frequency is CapitalizationFrequency.DAILY
                or (settle_at_end and next_date == ends_on)
                or (
                    terms.capitalization_frequency is CapitalizationFrequency.MONTHLY_CALENDAR_END
                    and next_date.month != current.month
                )
            )
            if capitalizes:
                gross = _rounded(pending, terms)
                tax = _rounded(max(gross, _ZERO) * terms.tax_rate.value, terms)
                net = gross - tax
                balance += net
                entries.append(
                    InterestScheduleEntry(
                        accrual_starts_on=period_start,
                        accrual_ends_on=next_date,
                        posting_date=next_date,
                        opening_balance=_money(period_opening, terms),
                        cashflow=_money(period_cashflow, terms),
                        gross_interest=_money(gross, terms),
                        tax=_money(tax, terms),
                        net_interest=_money(net, terms),
                        closing_balance=_money(balance, terms),
                    )
                )
                pending = _ZERO
                period_opening = balance
                period_cashflow = _ZERO
                period_start = next_date
            current = next_date
    return _Simulation(tuple(entries), balance, pending)


def _rate_on(terms: DepositTerms, value: date) -> Rate:
    for period in terms.rate_periods:
        if period.starts_on <= value < period.ends_on:
            return period.nominal_rate
    raise DomainError("no nominal rate covers accrual date")


def _net_pending(terms: DepositTerms, pending: Decimal) -> Decimal:
    gross = _rounded(pending, terms)
    tax = _rounded(max(gross, _ZERO) * terms.tax_rate.value, terms)
    return gross - tax


def _effective_yield(
    terms: DepositTerms,
    cashflows: tuple[tuple[date, DepositCashflow], ...],
    closes_on: date,
    closing_value: Decimal,
) -> Rate | None:
    dated_flows = [(value, -cashflow.amount.amount) for value, cashflow in cashflows]
    dated_flows.append((closes_on, closing_value))
    if not any(amount < 0 for _, amount in dated_flows) or not any(
        amount > 0 for _, amount in dated_flows
    ):
        return None

    def npv(rate: Decimal) -> Decimal:
        base = _ONE + rate
        return sum(
            (
                amount
                / (base ** day_count_fraction(terms.opened_on, value, terms.day_count_convention))
                for value, amount in dated_flows
            ),
            start=_ZERO,
        )

    with localcontext() as context:
        context.prec = 64
        lower = Decimal("-0.999999999999")
        upper = _ONE
        lower_value = npv(lower)
        upper_value = npv(upper)
        while lower_value * upper_value > 0 and upper < Decimal("1000000000000"):
            upper *= 2
            upper_value = npv(upper)
        if lower_value * upper_value > 0:
            return None
        for _ in range(192):
            middle = (lower + upper) / 2
            middle_value = npv(middle)
            if middle_value == 0:
                lower = upper = middle
                break
            if lower_value * middle_value <= 0:
                upper = middle
            else:
                lower = middle
                lower_value = middle_value
        result = ((lower + upper) / 2).quantize(Decimal("0.000000000001"))
    return Rate.of(result)


def _rounded(value: Decimal, terms: DepositTerms) -> Decimal:
    return terms.rounding_policy.round(value, terms.currency)


def _money(value: Decimal, terms: DepositTerms) -> Money:
    return Money.rounded(value, terms.currency, terms.rounding_policy)


def _is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
