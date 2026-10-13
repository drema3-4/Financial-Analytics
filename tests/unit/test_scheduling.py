from __future__ import annotations

from datetime import UTC, date, datetime, time
from uuid import UUID
from zoneinfo import ZoneInfo

from financial_analytics_domain import (
    CatchUpPolicy,
    Instant,
    MissingDayPolicy,
    Money,
    RecurrenceFrequency,
    RecurringOperation,
    RecurringRule,
    TransactionKind,
    first_occurrence,
    next_occurrence,
    occurrences_on_or_after,
)

OWNER = UUID("00000000-0000-0000-0000-000000000001")
ACCOUNT = UUID("00000000-0000-0000-0000-000000000002")
DESTINATION = UUID("00000000-0000-0000-0000-000000000003")


def _rule(
    *,
    frequency: RecurrenceFrequency,
    starts_on: date,
    local_time: time = time(9),
    timezone: str = "UTC",
    missing_day_policy: MissingDayPolicy = MissingDayPolicy.LAST_DAY,
    end_date: date | None = None,
) -> RecurringRule:
    return RecurringRule(
        id=UUID("00000000-0000-0000-0000-000000000004"),
        owner_id=OWNER,
        operation=RecurringOperation(
            kind=TransactionKind.TRANSFER,
            account_id=ACCOUNT,
            destination_account_id=DESTINATION,
            amount=Money.of("1.00", "USD"),
        ),
        frequency=frequency,
        starts_on=starts_on,
        local_time=local_time,
        timezone=timezone,
        missing_day_policy=missing_day_policy,
        catch_up_policy=CatchUpPolicy.ALL,
        end_date=end_date,
        next_occurrence_at=None,
    )


def _local_dates(rule: RecurringRule, count: int) -> list[date]:
    values = occurrences_on_or_after(
        rule,
        Instant(datetime(2000, 1, 1, tzinfo=UTC)),
        limit=count,
    )
    zone = ZoneInfo(rule.timezone)
    return [value.value.astimezone(zone).date() for value in values]


def test_monthly_missing_day_policy_preserves_anchor_without_drift() -> None:
    last_day = _rule(
        frequency=RecurrenceFrequency.MONTHLY,
        starts_on=date(2027, 1, 31),
        missing_day_policy=MissingDayPolicy.LAST_DAY,
    )
    skip = _rule(
        frequency=RecurrenceFrequency.MONTHLY,
        starts_on=date(2027, 1, 31),
        missing_day_policy=MissingDayPolicy.SKIP,
    )

    assert _local_dates(last_day, 4) == [
        date(2027, 1, 31),
        date(2027, 2, 28),
        date(2027, 3, 31),
        date(2027, 4, 30),
    ]
    assert _local_dates(skip, 4) == [
        date(2027, 1, 31),
        date(2027, 3, 31),
        date(2027, 5, 31),
        date(2027, 7, 31),
    ]


def test_yearly_leap_day_supports_last_day_and_skip() -> None:
    last_day = _rule(
        frequency=RecurrenceFrequency.YEARLY,
        starts_on=date(2024, 2, 29),
        missing_day_policy=MissingDayPolicy.LAST_DAY,
    )
    skip = _rule(
        frequency=RecurrenceFrequency.YEARLY,
        starts_on=date(2024, 2, 29),
        missing_day_policy=MissingDayPolicy.SKIP,
    )

    assert _local_dates(last_day, 3) == [
        date(2024, 2, 29),
        date(2025, 2, 28),
        date(2026, 2, 28),
    ]
    assert _local_dates(skip, 2) == [date(2024, 2, 29), date(2028, 2, 29)]


def test_dst_gap_moves_forward_and_fold_uses_first_instant() -> None:
    spring = _rule(
        frequency=RecurrenceFrequency.DAILY,
        starts_on=date(2026, 3, 8),
        local_time=time(2, 30),
        timezone="America/New_York",
    )
    first = first_occurrence(spring)
    assert first == Instant(datetime(2026, 3, 8, 7, 30, tzinfo=UTC))
    assert first is not None
    assert next_occurrence(spring, first) == Instant(datetime(2026, 3, 9, 6, 30, tzinfo=UTC))

    fall = _rule(
        frequency=RecurrenceFrequency.DAILY,
        starts_on=date(2026, 11, 1),
        local_time=time(1, 30),
        timezone="America/New_York",
    )
    assert first_occurrence(fall) == Instant(datetime(2026, 11, 1, 5, 30, tzinfo=UTC))


def test_end_date_is_inclusive_and_preview_does_not_create_state() -> None:
    rule = _rule(
        frequency=RecurrenceFrequency.DAILY,
        starts_on=date(2026, 10, 13),
        end_date=date(2026, 10, 14),
    )
    assert _local_dates(rule, 10) == [date(2026, 10, 13), date(2026, 10, 14)]
