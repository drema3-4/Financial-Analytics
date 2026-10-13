from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, localcontext
from enum import StrEnum
from statistics import median
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from financial_analytics_domain.errors import DomainError, OwnershipError
from financial_analytics_domain.ledger import (
    Account,
    Category,
    CategoryGroup,
    Transaction,
    TransactionKind,
)
from financial_analytics_domain.values import Currency, Money, RoundingPolicy

ANOMALY_POLICY_VERSION = "median-mad-v1"
ANOMALY_BASELINE_BUCKETS = 6
ANOMALY_MINIMUM_BUCKETS = 3
RATIO_QUANTUM = Decimal("0.000001")


class PeriodGranularity(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class CurrencyMode(StrEnum):
    EMPTY = "empty"
    SINGLE = "single_currency"
    SEPARATED = "separated_by_currency"


@dataclass(frozen=True, slots=True)
class AnalyticsPeriod:
    start: date
    end: date
    timezone: str
    granularity: PeriodGranularity

    def __post_init__(self) -> None:
        if isinstance(self.start, datetime) or isinstance(self.end, datetime):
            raise TypeError("analytics boundaries must be dates")
        if self.start >= self.end:
            raise DomainError("analytics period end must be after start")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise DomainError("analytics timezone must be an IANA timezone") from error
        if not _is_aligned(self.start, self.granularity):
            raise DomainError("analytics period start is not aligned to granularity")
        if not _is_aligned(self.end, self.granularity):
            raise DomainError("analytics period end is not aligned to granularity")
        if _bucket_count(self.start, self.end, self.granularity) > 366:
            raise DomainError("analytics period cannot contain more than 366 buckets")

    @property
    def start_at(self) -> datetime:
        return local_midnight(self.start, self.timezone)

    @property
    def end_at(self) -> datetime:
        return local_midnight(self.end, self.timezone)


@dataclass(frozen=True, slots=True)
class Evidence:
    transaction_ids: tuple[UUID, ...] = ()
    posting_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class MoneyMetric:
    value: Money
    formula: str
    evidence: Evidence


@dataclass(frozen=True, slots=True)
class RatioMetric:
    value: Decimal | None
    formula: str
    numerator: Money
    denominator: Money
    evidence: Evidence


@dataclass(frozen=True, slots=True)
class BreakdownItem:
    flow_type: str
    id: UUID | None
    name: str
    amount: Money
    evidence: Evidence


@dataclass(frozen=True, slots=True)
class CurrencyAnalytics:
    currency: Currency
    income: MoneyMetric
    expense: MoneyMetric
    cash_flow: MoneyMetric
    savings: MoneyMetric
    mandatory_expense: MoneyMetric
    mandatory_expense_share: RatioMetric
    savings_rate: RatioMetric
    opening_net_worth: MoneyMetric
    closing_net_worth: MoneyMetric
    net_worth_change: MoneyMetric
    category_breakdown: tuple[BreakdownItem, ...]
    group_breakdown: tuple[BreakdownItem, ...]


@dataclass(frozen=True, slots=True)
class AnalyticsBucket:
    start: date
    end: date
    is_complete: bool
    currencies: tuple[CurrencyAnalytics, ...]


@dataclass(frozen=True, slots=True)
class ComparisonMetric:
    current: Money
    previous: Money
    delta: Money
    change_rate: Decimal | None


@dataclass(frozen=True, slots=True)
class CurrencyComparison:
    currency: Currency
    income: ComparisonMetric
    expense: ComparisonMetric
    cash_flow: ComparisonMetric
    savings: ComparisonMetric
    net_worth: ComparisonMetric


@dataclass(frozen=True, slots=True)
class PeriodComparison:
    current_start: datetime
    current_end: datetime
    previous_start: datetime
    previous_end: datetime
    current_is_complete: bool
    currencies: tuple[CurrencyComparison, ...]


@dataclass(frozen=True, slots=True)
class AnomalyFlag:
    bucket_start: date
    bucket_end: date
    metric: str
    direction: str
    observed: Money
    baseline: Money
    deviation: Money
    threshold: Money
    rationale: str
    baseline_bucket_count: int
    evidence: Evidence


@dataclass(frozen=True, slots=True)
class AnalyticsReport:
    period: AnalyticsPeriod
    data_through: datetime
    currency_mode: CurrencyMode
    combined_currency: Currency | None
    totals: tuple[CurrencyAnalytics, ...]
    buckets: tuple[AnalyticsBucket, ...]
    comparison: PeriodComparison
    anomalies: tuple[AnomalyFlag, ...]


@dataclass(frozen=True, slots=True)
class _Fact:
    transaction_id: UUID
    posting_ids: tuple[UUID, ...]
    occurred_at: datetime
    currency: Currency
    effective_kind: TransactionKind
    category_id: UUID | None
    asset_delta: Decimal


def local_midnight(value: date, timezone: str) -> datetime:
    zone = ZoneInfo(timezone)
    local = datetime.combine(value, time.min)
    fold_zero = local.replace(tzinfo=zone, fold=0)
    zero_utc = fold_zero.astimezone(UTC)
    zero_roundtrip = zero_utc.astimezone(zone).replace(tzinfo=None)
    if zero_roundtrip == local:
        return zero_utc
    fold_one = local.replace(tzinfo=zone, fold=1)
    one_utc = fold_one.astimezone(UTC)
    one_roundtrip = one_utc.astimezone(zone).replace(tzinfo=None)
    forward = [
        (roundtrip, instant)
        for roundtrip, instant in ((zero_roundtrip, zero_utc), (one_roundtrip, one_utc))
        if roundtrip > local
    ]
    if not forward:
        raise DomainError("timezone transition could not resolve local period boundary")
    return min(forward, key=lambda item: item[0])[1]


def period_buckets(period: AnalyticsPeriod) -> tuple[tuple[date, date], ...]:
    result: list[tuple[date, date]] = []
    current = period.start
    while current < period.end:
        following = min(_advance(current, period.granularity, 1), period.end)
        result.append((current, following))
        current = following
    return tuple(result)


def default_period(now: datetime, timezone: str, granularity: PeriodGranularity) -> AnalyticsPeriod:
    _require_aware(now)
    local_date = now.astimezone(ZoneInfo(timezone)).date()
    if granularity is PeriodGranularity.DAY:
        start = local_date
    elif granularity is PeriodGranularity.WEEK:
        start = local_date - timedelta(days=local_date.weekday())
    else:
        start = local_date.replace(day=1)
    return AnalyticsPeriod(start, _advance(start, granularity, 1), timezone, granularity)


def build_analytics_report(
    *,
    accounts: tuple[Account, ...],
    categories: tuple[Category, ...],
    groups: tuple[CategoryGroup, ...],
    transactions: tuple[Transaction, ...],
    period: AnalyticsPeriod,
    now: datetime,
) -> AnalyticsReport:
    _require_aware(now)
    now_utc = now.astimezone(UTC)
    _validate_owners(accounts, categories, groups, transactions)
    facts = _facts(accounts, transactions)
    category_map = {item.id: item for item in categories}
    group_map = {item.id: item for item in groups}
    currencies = tuple(
        sorted(
            {item.currency for item in accounts if item.kind.is_asset}
            | {item.currency for item in facts},
            key=lambda item: item.code,
        )
    )
    requested_end = period.end_at
    effective_end = min(requested_end, now_utc)
    if effective_end < period.start_at:
        effective_end = period.start_at
    totals = tuple(
        _summarize_currency(
            facts,
            category_map,
            group_map,
            currency,
            period.start_at,
            effective_end,
        )
        for currency in currencies
    )
    buckets = tuple(
        AnalyticsBucket(
            start=bucket_start,
            end=bucket_end,
            is_complete=local_midnight(bucket_end, period.timezone) <= now_utc,
            currencies=tuple(
                _summarize_currency(
                    facts,
                    category_map,
                    group_map,
                    currency,
                    local_midnight(bucket_start, period.timezone),
                    max(
                        local_midnight(bucket_start, period.timezone),
                        min(local_midnight(bucket_end, period.timezone), now_utc),
                    ),
                )
                for currency in currencies
            ),
        )
        for bucket_start, bucket_end in period_buckets(period)
    )
    comparison = _comparison(
        facts,
        category_map,
        group_map,
        currencies,
        period,
        effective_end,
        now_utc,
    )
    anomalies = _anomalies(
        facts,
        category_map,
        group_map,
        currencies,
        period,
        now_utc,
    )
    if not currencies:
        currency_mode = CurrencyMode.EMPTY
        combined_currency = None
    elif len(currencies) == 1:
        currency_mode = CurrencyMode.SINGLE
        combined_currency = currencies[0]
    else:
        currency_mode = CurrencyMode.SEPARATED
        combined_currency = None
    return AnalyticsReport(
        period=period,
        data_through=effective_end,
        currency_mode=currency_mode,
        combined_currency=combined_currency,
        totals=totals,
        buckets=buckets,
        comparison=comparison,
        anomalies=anomalies,
    )


def _validate_owners(
    accounts: tuple[Account, ...],
    categories: tuple[Category, ...],
    groups: tuple[CategoryGroup, ...],
    transactions: tuple[Transaction, ...],
) -> None:
    owners = {
        *(item.owner_id for item in accounts),
        *(item.owner_id for item in categories),
        *(item.owner_id for item in groups),
        *(item.owner_id for item in transactions),
    }
    if len(owners) > 1:
        raise OwnershipError("analytics input must belong to one owner")


def _facts(
    accounts: tuple[Account, ...], transactions: tuple[Transaction, ...]
) -> tuple[_Fact, ...]:
    asset_ids = {item.id for item in accounts if item.kind.is_asset}
    transaction_map = {item.id: item for item in transactions}
    result: list[_Fact] = []
    for transaction in transactions:
        original = None
        if transaction.kind is TransactionKind.REVERSAL:
            if transaction.reversal_of_id is None:
                raise DomainError("analytics reversal is missing its causal link")
            original = transaction_map.get(transaction.reversal_of_id)
        if transaction.kind is TransactionKind.REVERSAL and original is None:
            raise DomainError("analytics reversal is missing its original transaction")
        effective = original if original is not None else transaction
        asset_postings = tuple(
            posting for posting in transaction.postings if posting.account_id in asset_ids
        )
        result.append(
            _Fact(
                transaction_id=transaction.id,
                posting_ids=tuple(item.id for item in asset_postings),
                occurred_at=transaction.occurred_at.value,
                currency=transaction.currency,
                effective_kind=effective.kind,
                category_id=effective.category_id,
                asset_delta=sum(
                    (item.amount.amount for item in asset_postings), start=Decimal("0")
                ),
            )
        )
    return tuple(result)


def _summarize_currency(
    facts: tuple[_Fact, ...],
    categories: dict[UUID, Category],
    groups: dict[UUID, CategoryGroup],
    currency: Currency,
    start_at: datetime,
    end_at: datetime,
) -> CurrencyAnalytics:
    selected = tuple(
        item
        for item in facts
        if item.currency == currency and start_at <= item.occurred_at < end_at
    )
    income_facts = tuple(
        item
        for item in selected
        if item.effective_kind in {TransactionKind.INCOME, TransactionKind.INTEREST}
    )
    expense_facts = tuple(
        item for item in selected if item.effective_kind is TransactionKind.EXPENSE
    )
    mandatory_facts = tuple(
        item
        for item in expense_facts
        if item.category_id is not None
        and categories.get(item.category_id) is not None
        and categories[item.category_id].is_mandatory
    )
    income_value = sum((item.asset_delta for item in income_facts), start=Decimal("0"))
    expense_value = sum((-item.asset_delta for item in expense_facts), start=Decimal("0"))
    mandatory_value = sum((-item.asset_delta for item in mandatory_facts), start=Decimal("0"))
    opening_facts = tuple(
        item for item in facts if item.currency == currency and item.occurred_at < start_at
    )
    closing_facts = tuple(
        item for item in facts if item.currency == currency and item.occurred_at < end_at
    )
    opening_value = sum((item.asset_delta for item in opening_facts), start=Decimal("0"))
    closing_value = sum((item.asset_delta for item in closing_facts), start=Decimal("0"))
    income = _metric(currency, income_value, "sum(external income asset postings)", income_facts)
    expense = _metric(currency, expense_value, "sum(-expense asset postings)", expense_facts)
    cash_flow = _metric(
        currency,
        income_value - expense_value,
        "income - expense; transfers and adjustments excluded",
        income_facts + expense_facts,
    )
    savings = _metric(
        currency,
        income_value - expense_value,
        "income - expense",
        income_facts + expense_facts,
    )
    mandatory = _metric(
        currency,
        mandatory_value,
        "sum(-expense asset postings where category.is_mandatory)",
        mandatory_facts,
    )
    opening = _metric(
        currency,
        opening_value,
        "sum(asset postings before period start)",
        opening_facts,
    )
    closing = _metric(
        currency,
        closing_value,
        "sum(asset postings before data_through)",
        closing_facts,
    )
    net_worth_change = _metric(
        currency,
        closing_value - opening_value,
        "closing_net_worth - opening_net_worth",
        selected,
    )
    return CurrencyAnalytics(
        currency=currency,
        income=income,
        expense=expense,
        cash_flow=cash_flow,
        savings=savings,
        mandatory_expense=mandatory,
        mandatory_expense_share=_ratio_metric(
            mandatory,
            expense,
            "mandatory_expense / expense when expense > 0",
        ),
        savings_rate=_ratio_metric(
            savings,
            income,
            "(income - expense) / income when income > 0",
        ),
        opening_net_worth=opening,
        closing_net_worth=closing,
        net_worth_change=net_worth_change,
        category_breakdown=_category_breakdown(currency, income_facts + expense_facts, categories),
        group_breakdown=_group_breakdown(
            currency, income_facts + expense_facts, categories, groups
        ),
    )


def _metric(
    currency: Currency, amount: Decimal, formula: str, facts: tuple[_Fact, ...]
) -> MoneyMetric:
    return MoneyMetric(Money.of(amount, currency), formula, _evidence(facts))


def _ratio_metric(numerator: MoneyMetric, denominator: MoneyMetric, formula: str) -> RatioMetric:
    value = None
    if denominator.value.amount > 0:
        with localcontext() as context:
            context.prec = 50
            value = (numerator.value.amount / denominator.value.amount).quantize(RATIO_QUANTUM)
    return RatioMetric(
        value=value,
        formula=formula,
        numerator=numerator.value,
        denominator=denominator.value,
        evidence=_merge_evidence(numerator.evidence, denominator.evidence),
    )


def _category_breakdown(
    currency: Currency,
    facts: tuple[_Fact, ...],
    categories: dict[UUID, Category],
) -> tuple[BreakdownItem, ...]:
    grouped: dict[tuple[str, UUID | None, str], list[_Fact]] = {}
    for item in facts:
        category = categories.get(item.category_id) if item.category_id is not None else None
        name = (
            "Deposit interest"
            if item.effective_kind is TransactionKind.INTEREST
            else (category.name if category is not None else "Uncategorized")
        )
        flow_type = (
            "income"
            if item.effective_kind in {TransactionKind.INCOME, TransactionKind.INTEREST}
            else "expense"
        )
        grouped.setdefault((flow_type, item.category_id, name), []).append(item)
    result: list[BreakdownItem] = []
    for (flow_type, category_id, name), items in grouped.items():
        amount = sum((_flow_amount(item) for item in items), start=Decimal("0"))
        result.append(
            BreakdownItem(
                flow_type,
                category_id,
                name,
                Money.of(amount, currency),
                _evidence(tuple(items)),
            )
        )
    return tuple(sorted(result, key=lambda item: (item.flow_type, item.name, str(item.id or ""))))


def _group_breakdown(
    currency: Currency,
    facts: tuple[_Fact, ...],
    categories: dict[UUID, Category],
    groups: dict[UUID, CategoryGroup],
) -> tuple[BreakdownItem, ...]:
    grouped: dict[tuple[str, UUID | None, str], list[_Fact]] = {}
    for item in facts:
        category = categories.get(item.category_id) if item.category_id is not None else None
        group = (
            groups.get(category.group_id) if category is not None and category.group_id else None
        )
        name = group.name if group is not None else "Ungrouped"
        flow_type = (
            "income"
            if item.effective_kind in {TransactionKind.INCOME, TransactionKind.INTEREST}
            else "expense"
        )
        grouped.setdefault((flow_type, None if group is None else group.id, name), []).append(item)
    result: list[BreakdownItem] = []
    for (flow_type, group_id, name), items in grouped.items():
        amount = sum((_flow_amount(item) for item in items), start=Decimal("0"))
        result.append(
            BreakdownItem(
                flow_type,
                group_id,
                name,
                Money.of(amount, currency),
                _evidence(tuple(items)),
            )
        )
    return tuple(sorted(result, key=lambda item: (item.flow_type, item.name, str(item.id or ""))))


def _flow_amount(fact: _Fact) -> Decimal:
    if fact.effective_kind in {TransactionKind.INCOME, TransactionKind.INTEREST}:
        return fact.asset_delta
    if fact.effective_kind is TransactionKind.EXPENSE:
        return -fact.asset_delta
    return Decimal("0")


def _comparison(
    facts: tuple[_Fact, ...],
    categories: dict[UUID, Category],
    groups: dict[UUID, CategoryGroup],
    currencies: tuple[Currency, ...],
    period: AnalyticsPeriod,
    effective_end: datetime,
    now: datetime,
) -> PeriodComparison:
    bucket_count = len(period_buckets(period))
    previous_start_date = _advance(period.start, period.granularity, -bucket_count)
    previous_start = local_midnight(previous_start_date, period.timezone)
    if effective_end >= period.end_at:
        previous_end = period.start_at
    else:
        previous_end = _shift_local_datetime(
            effective_end, period.timezone, period.granularity, -bucket_count
        )
    current_values = {
        item.currency: item
        for item in (
            _summarize_currency(
                facts,
                categories,
                groups,
                currency,
                period.start_at,
                effective_end,
            )
            for currency in currencies
        )
    }
    previous_values = {
        item.currency: item
        for item in (
            _summarize_currency(
                facts,
                categories,
                groups,
                currency,
                previous_start,
                previous_end,
            )
            for currency in currencies
        )
    }
    comparisons: list[CurrencyComparison] = []
    for currency in currencies:
        current = current_values[currency]
        previous = previous_values[currency]
        comparisons.append(
            CurrencyComparison(
                currency=currency,
                income=_comparison_metric(current.income.value, previous.income.value),
                expense=_comparison_metric(current.expense.value, previous.expense.value),
                cash_flow=_comparison_metric(current.cash_flow.value, previous.cash_flow.value),
                savings=_comparison_metric(current.savings.value, previous.savings.value),
                net_worth=_comparison_metric(
                    current.closing_net_worth.value, previous.closing_net_worth.value
                ),
            )
        )
    return PeriodComparison(
        current_start=period.start_at,
        current_end=effective_end,
        previous_start=previous_start,
        previous_end=previous_end,
        current_is_complete=period.end_at <= now,
        currencies=tuple(comparisons),
    )


def _comparison_metric(current: Money, previous: Money) -> ComparisonMetric:
    delta = current - previous
    rate = None
    if previous.amount != 0:
        with localcontext() as context:
            context.prec = 50
            rate = (delta.amount / abs(previous.amount)).quantize(RATIO_QUANTUM)
    return ComparisonMetric(current, previous, delta, rate)


def _anomalies(
    facts: tuple[_Fact, ...],
    categories: dict[UUID, Category],
    groups: dict[UUID, CategoryGroup],
    currencies: tuple[Currency, ...],
    period: AnalyticsPeriod,
    now: datetime,
) -> tuple[AnomalyFlag, ...]:
    result: list[AnomalyFlag] = []
    for bucket_start, bucket_end in period_buckets(period):
        bucket_start_at = local_midnight(bucket_start, period.timezone)
        bucket_end_at = local_midnight(bucket_end, period.timezone)
        if bucket_end_at > now:
            continue
        for currency in currencies:
            observed_summary = _summarize_currency(
                facts, categories, groups, currency, bucket_start_at, bucket_end_at
            )
            for metric_name in ("income", "expense"):
                history: list[Decimal] = []
                for offset in range(ANOMALY_BASELINE_BUCKETS, 0, -1):
                    baseline_start_date = _advance(bucket_start, period.granularity, -offset)
                    baseline_end_date = _advance(baseline_start_date, period.granularity, 1)
                    baseline_summary = _summarize_currency(
                        facts,
                        categories,
                        groups,
                        currency,
                        local_midnight(baseline_start_date, period.timezone),
                        local_midnight(baseline_end_date, period.timezone),
                    )
                    history.append(getattr(baseline_summary, metric_name).value.amount)
                if len(history) < ANOMALY_MINIMUM_BUCKETS:
                    continue
                metric = getattr(observed_summary, metric_name)
                flag = _anomaly_flag(
                    bucket_start,
                    bucket_end,
                    metric_name,
                    metric,
                    history,
                )
                if flag is not None:
                    result.append(flag)
    return tuple(result)


def _anomaly_flag(
    bucket_start: date,
    bucket_end: date,
    metric_name: str,
    metric: MoneyMetric,
    history: list[Decimal],
) -> AnomalyFlag | None:
    currency = metric.value.currency
    baseline_raw = Decimal(median(history))
    deviations = [abs(item - baseline_raw) for item in history]
    mad_raw = Decimal(median(deviations))
    threshold_raw = max(abs(baseline_raw) * Decimal("0.50"), mad_raw * Decimal("3"))
    baseline = Money.rounded(baseline_raw, currency, RoundingPolicy.HALF_EVEN)
    threshold = Money.rounded(threshold_raw, currency, RoundingPolicy.HALF_EVEN)
    deviation = metric.value - baseline
    if deviation.amount == 0 or abs(deviation.amount) < threshold.amount:
        return None
    if threshold.amount == 0 and metric.value.amount == 0:
        return None
    direction = "increase" if deviation.amount > 0 else "decrease"
    rationale = (
        f"{metric_name} {direction}: absolute deviation meets median-mad-v1 threshold "
        f"from {len(history)} completed prior {metric_name} buckets"
    )
    return AnomalyFlag(
        bucket_start=bucket_start,
        bucket_end=bucket_end,
        metric=metric_name,
        direction=direction,
        observed=metric.value,
        baseline=baseline,
        deviation=deviation,
        threshold=threshold,
        rationale=rationale,
        baseline_bucket_count=len(history),
        evidence=metric.evidence,
    )


def _evidence(facts: tuple[_Fact, ...]) -> Evidence:
    return Evidence(
        transaction_ids=tuple(sorted({item.transaction_id for item in facts}, key=str)),
        posting_ids=tuple(
            sorted({posting_id for item in facts for posting_id in item.posting_ids}, key=str)
        ),
    )


def _merge_evidence(*items: Evidence) -> Evidence:
    return Evidence(
        transaction_ids=tuple(
            sorted({value for item in items for value in item.transaction_ids}, key=str)
        ),
        posting_ids=tuple(sorted({value for item in items for value in item.posting_ids}, key=str)),
    )


def _is_aligned(value: date, granularity: PeriodGranularity) -> bool:
    if granularity is PeriodGranularity.DAY:
        return True
    if granularity is PeriodGranularity.WEEK:
        return value.weekday() == 0
    return value.day == 1


def _bucket_count(start: date, end: date, granularity: PeriodGranularity) -> int:
    if granularity is PeriodGranularity.DAY:
        return (end - start).days
    if granularity is PeriodGranularity.WEEK:
        return (end - start).days // 7
    return (end.year - start.year) * 12 + end.month - start.month


def _advance(value: date, granularity: PeriodGranularity, amount: int) -> date:
    if granularity is PeriodGranularity.DAY:
        return value + timedelta(days=amount)
    if granularity is PeriodGranularity.WEEK:
        return value + timedelta(days=7 * amount)
    month_index = value.year * 12 + value.month - 1 + amount
    year, month_zero = divmod(month_index, 12)
    return date(year, month_zero + 1, 1)


def _shift_local_datetime(
    value: datetime,
    timezone: str,
    granularity: PeriodGranularity,
    amount: int,
) -> datetime:
    local = value.astimezone(ZoneInfo(timezone))
    if granularity is PeriodGranularity.DAY:
        shifted = local + timedelta(days=amount)
    elif granularity is PeriodGranularity.WEEK:
        shifted = local + timedelta(days=7 * amount)
    else:
        month_index = local.year * 12 + local.month - 1 + amount
        year, month_zero = divmod(month_index, 12)
        day = min(local.day, calendar.monthrange(year, month_zero + 1)[1])
        shifted = local.replace(year=year, month=month_zero + 1, day=day)
    return shifted.astimezone(UTC)


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("analytics clock must be timezone-aware")
