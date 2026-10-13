from __future__ import annotations

import calendar
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from financial_analytics_domain.errors import DomainError
from financial_analytics_domain.ledger import TransactionKind
from financial_analytics_domain.values import Instant, Money


class RecurrenceFrequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"


class MissingDayPolicy(StrEnum):
    LAST_DAY = "last_day"
    SKIP = "skip"


class CatchUpPolicy(StrEnum):
    ALL = "all"
    LATEST = "latest"


class RecurringRuleStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class OutboxJobState(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    SUCCEEDED = "succeeded"
    DEAD_LETTER = "dead_letter"


@dataclass(frozen=True, slots=True)
class RecurringOperation:
    kind: TransactionKind
    account_id: UUID
    amount: Money
    description: str = ""
    category_id: UUID | None = None
    destination_account_id: UUID | None = None
    tag_ids: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in {
            TransactionKind.INCOME,
            TransactionKind.EXPENSE,
            TransactionKind.TRANSFER,
        }:
            raise DomainError("recurring rules support income, expense, and transfer only")
        if not self.amount.is_positive():
            raise DomainError("recurring amount must be positive")
        if len(self.description) > 1000:
            raise DomainError("recurring description is too long")
        if len(set(self.tag_ids)) != len(self.tag_ids):
            raise DomainError("recurring operation tags must be unique")
        if self.kind in {TransactionKind.INCOME, TransactionKind.EXPENSE}:
            if self.category_id is None or self.destination_account_id is not None:
                raise DomainError("income and expense require one category and no destination")
        elif self.category_id is not None or self.destination_account_id is None:
            raise DomainError("transfer requires a destination and no category")
        if self.destination_account_id == self.account_id:
            raise DomainError("transfer accounts must differ")


@dataclass(frozen=True, slots=True)
class RecurringRule:
    id: UUID
    owner_id: UUID
    operation: RecurringOperation
    frequency: RecurrenceFrequency
    starts_on: date
    local_time: time
    timezone: str
    missing_day_policy: MissingDayPolicy
    catch_up_policy: CatchUpPolicy
    end_date: date | None
    next_occurrence_at: Instant | None
    status: RecurringRuleStatus = RecurringRuleStatus.ACTIVE
    version: int = 1

    def __post_init__(self) -> None:
        if isinstance(self.starts_on, datetime) or isinstance(self.end_date, datetime):
            raise TypeError("schedule boundaries must be local dates")
        if self.local_time.tzinfo is not None:
            raise DomainError("local_time must not contain a UTC offset")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise DomainError("timezone must be an IANA timezone") from error
        if self.end_date is not None and self.end_date < self.starts_on:
            raise DomainError("end_date must not be earlier than starts_on")
        if self.version < 1:
            raise DomainError("recurring rule version must be positive")
        if self.status is RecurringRuleStatus.COMPLETED and self.next_occurrence_at is not None:
            raise DomainError("completed recurring rule cannot have a next occurrence")

    def with_next(self, value: Instant | None) -> RecurringRule:
        status = self.status
        if value is None and status is RecurringRuleStatus.ACTIVE:
            status = RecurringRuleStatus.COMPLETED
        return replace(self, next_occurrence_at=value, status=status)


@dataclass(frozen=True, slots=True)
class OutboxJob:
    id: UUID
    owner_id: UUID
    rule_id: UUID
    occurrence_at: Instant
    operation: RecurringOperation
    dedup_key: str
    state: OutboxJobState
    attempts: int
    max_attempts: int
    available_at: Instant
    lease_owner: str | None = None
    lease_expires_at: Instant | None = None
    last_error: str | None = None
    transaction_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.attempts < 0 or self.max_attempts < 1 or self.attempts > self.max_attempts:
            raise DomainError("job attempts are outside the allowed range")
        if not self.dedup_key:
            raise DomainError("job dedup key must not be empty")
        if (self.lease_owner is None) != (self.lease_expires_at is None):
            raise DomainError("job lease owner and expiry must be supplied together")


def first_occurrence(rule: RecurringRule) -> Instant | None:
    return _instant_for_candidate(rule, rule.starts_on)


def next_occurrence(rule: RecurringRule, after: Instant) -> Instant | None:
    local_date = after.value.astimezone(ZoneInfo(rule.timezone)).date()
    candidate = local_date
    while True:
        candidate = _next_candidate_date(rule, candidate)
        if rule.end_date is not None and candidate > rule.end_date:
            return None
        occurrence = _instant_for_candidate(rule, candidate)
        if occurrence is not None and occurrence.value > after.value:
            return occurrence


def occurrences_on_or_after(
    rule: RecurringRule,
    from_at: Instant,
    *,
    limit: int,
) -> tuple[Instant, ...]:
    if limit < 1:
        raise ValueError("limit must be positive")
    occurrence = first_occurrence(rule)
    values: list[Instant] = []
    while occurrence is not None and len(values) < limit:
        if occurrence.value >= from_at.value:
            values.append(occurrence)
        occurrence = next_occurrence(rule, occurrence)
    return tuple(values)


def latest_due_occurrence(
    rule: RecurringRule, now: Instant
) -> tuple[Instant | None, Instant | None]:
    occurrence = rule.next_occurrence_at
    latest: Instant | None = None
    while occurrence is not None and occurrence.value <= now.value:
        latest = occurrence
        occurrence = next_occurrence(rule, occurrence)
    return latest, occurrence


def occurrence_dedup_key(rule_id: UUID, occurrence_at: Instant) -> str:
    timestamp = occurrence_at.value.isoformat().replace("+00:00", "Z")
    return f"{rule_id}:{timestamp}"


def _next_candidate_date(rule: RecurringRule, current: date) -> date:
    if rule.frequency is RecurrenceFrequency.DAILY:
        return current + timedelta(days=1)
    if rule.frequency is RecurrenceFrequency.WEEKLY:
        return current + timedelta(days=7)
    if rule.frequency is RecurrenceFrequency.MONTHLY:
        year, month = current.year, current.month + 1
        if month == 13:
            year, month = year + 1, 1
        return _month_date(rule, year, month)
    return _year_date(rule, current.year + 1)


def _month_date(rule: RecurringRule, year: int, month: int) -> date:
    anchor_day = rule.starts_on.day
    while True:
        last_day = calendar.monthrange(year, month)[1]
        if anchor_day <= last_day:
            return date(year, month, anchor_day)
        if rule.missing_day_policy is MissingDayPolicy.LAST_DAY:
            return date(year, month, last_day)
        month += 1
        if month == 13:
            year, month = year + 1, 1


def _year_date(rule: RecurringRule, year: int) -> date:
    month, day = rule.starts_on.month, rule.starts_on.day
    while True:
        try:
            return date(year, month, day)
        except ValueError:
            if rule.missing_day_policy is MissingDayPolicy.LAST_DAY:
                return date(year, month, calendar.monthrange(year, month)[1])
            year += 1


def _instant_for_candidate(rule: RecurringRule, candidate: date) -> Instant | None:
    if rule.end_date is not None and candidate > rule.end_date:
        return None
    local = datetime.combine(candidate, rule.local_time)
    zone = ZoneInfo(rule.timezone)
    fold_zero = local.replace(tzinfo=zone, fold=0)
    zero_utc = fold_zero.astimezone(UTC)
    zero_roundtrip = zero_utc.astimezone(zone).replace(tzinfo=None)
    if zero_roundtrip == local:
        return Instant(zero_utc)

    fold_one = local.replace(tzinfo=zone, fold=1)
    one_utc = fold_one.astimezone(UTC)
    one_roundtrip = one_utc.astimezone(zone).replace(tzinfo=None)
    forward = [
        (roundtrip, value)
        for roundtrip, value in ((zero_roundtrip, zero_utc), (one_roundtrip, one_utc))
        if roundtrip > local
    ]
    if not forward:
        raise DomainError("timezone transition could not resolve local occurrence")
    _, resolved = min(forward, key=lambda item: item[0])
    return Instant(resolved)
