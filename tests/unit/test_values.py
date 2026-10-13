from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, cast

import pytest

from financial_analytics_domain import (
    Currency,
    DateRange,
    Instant,
    Money,
    Rate,
    RoundingPolicy,
)
from financial_analytics_domain.errors import (
    CurrencyMismatchError,
    FloatNotAllowedError,
    PrecisionError,
)


def test_money_rejects_float_and_implicit_rounding() -> None:
    with pytest.raises(FloatNotAllowedError):
        Money.of(cast(Any, 1.1), "RUB")
    with pytest.raises(FloatNotAllowedError):
        Rate.of(cast(Any, 0.1))
    with pytest.raises(PrecisionError):
        Money.of("1.001", "RUB")


def test_rounding_policy_is_explicit_and_currency_aware() -> None:
    rub = Currency("RUB")

    assert Money.rounded("1.005", rub, RoundingPolicy.HALF_EVEN).amount == Decimal("1.00")
    assert Money.rounded("1.005", rub, RoundingPolicy.HALF_UP).amount == Decimal("1.01")
    assert Money.of("10", "JPY").amount == Decimal("10")
    assert Money.of("10.001", "KWD").amount == Decimal("10.001")
    assert Money.of("99999999999999999999999999999.99", rub).amount == Decimal(
        "99999999999999999999999999999.99"
    )
    with pytest.raises(PrecisionError):
        Money.of("100000000000000000000000000000", rub)


def test_money_arithmetic_requires_same_currency() -> None:
    with pytest.raises(CurrencyMismatchError):
        _ = Money.of("1", "RUB") + Money.of("1", "USD")


def test_rate_application_uses_selected_rounding_policy() -> None:
    result = Rate.of("0.125").apply(Money.of("10.04", "RUB"), RoundingPolicy.HALF_EVEN)

    assert result == Money.of("1.26", "RUB")


def test_date_range_is_half_open() -> None:
    period = DateRange(date(2026, 1, 1), date(2026, 2, 1))

    assert period.contains(date(2026, 1, 1))
    assert not period.contains(date(2026, 2, 1))
    with pytest.raises(ValueError):
        DateRange(date(2026, 1, 1), date(2026, 1, 1))


def test_instant_requires_timezone_and_normalizes_to_utc() -> None:
    with pytest.raises(ValueError):
        Instant(datetime(2026, 1, 1))

    source = datetime(2026, 1, 1, 4, tzinfo=timezone(timedelta(hours=4)))
    instant = Instant(source)

    assert instant.value == datetime(2026, 1, 1, tzinfo=UTC)
    assert instant.value.tzinfo is UTC
