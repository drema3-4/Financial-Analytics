from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from enum import StrEnum
from typing import Self

from financial_analytics_domain.errors import FloatNotAllowedError, PrecisionError

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_THREE_DECIMAL_CURRENCIES = frozenset({"BHD", "JOD", "KWD", "OMR", "TND"})
_ZERO_DECIMAL_CURRENCIES = frozenset(
    {
        "BIF",
        "CLP",
        "DJF",
        "GNF",
        "ISK",
        "JPY",
        "KMF",
        "KRW",
        "PYG",
        "RWF",
        "UGX",
        "UYI",
        "VND",
        "VUV",
        "XAF",
        "XOF",
        "XPF",
    }
)


def _decimal(value: Decimal | int | str, *, field: str) -> Decimal:
    if isinstance(value, (float, bool)):
        raise FloatNotAllowedError(f"{field} must not be a float or bool")
    if not isinstance(value, (Decimal, int, str)):
        raise TypeError(f"{field} must be Decimal, int, or str")
    try:
        result = value if isinstance(value, Decimal) else Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{field} is not a decimal value") from error
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


@dataclass(frozen=True, slots=True)
class Currency:
    """An ISO 4217-shaped code and its accounting minor-unit precision."""

    code: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or _CURRENCY_RE.fullmatch(self.code) is None:
            raise ValueError("currency must be a three-letter uppercase code")

    @property
    def minor_units(self) -> int:
        if self.code in _ZERO_DECIMAL_CURRENCIES:
            return 0
        if self.code in _THREE_DECIMAL_CURRENCIES:
            return 3
        return 2

    @property
    def quantum(self) -> Decimal:
        return Decimal(1).scaleb(-self.minor_units)

    def __str__(self) -> str:
        return self.code


class RoundingPolicy(StrEnum):
    HALF_EVEN = "half_even"
    HALF_UP = "half_up"

    def round(self, value: Decimal | int | str, currency: Currency) -> Decimal:
        exact = _decimal(value, field="value")
        mode = ROUND_HALF_EVEN if self is RoundingPolicy.HALF_EVEN else ROUND_HALF_UP
        with localcontext() as context:
            context.prec = max(64, len(exact.as_tuple().digits) + currency.minor_units + 1)
            return exact.quantize(currency.quantum, rounding=mode)


@dataclass(frozen=True, slots=True)
class Money:
    """Exact money; construction never rounds implicitly."""

    amount: Decimal
    currency: Currency

    STORAGE_PRECISION = 38
    STORAGE_SCALE = 9

    def __post_init__(self) -> None:
        exact = _decimal(self.amount, field="amount")
        with localcontext() as context:
            context.prec = max(self.STORAGE_PRECISION, len(exact.as_tuple().digits) + 1)
            quantized = exact.quantize(self.currency.quantum)
        if exact != quantized:
            raise PrecisionError(
                f"{self.currency.code} permits {self.currency.minor_units} fractional digits"
            )
        if exact.copy_abs() >= Decimal(10) ** (self.STORAGE_PRECISION - self.STORAGE_SCALE):
            raise PrecisionError("amount exceeds NUMERIC(38, 9) storage capacity")
        object.__setattr__(self, "amount", quantized)

    @classmethod
    def of(cls, value: Decimal | int | str, currency: Currency | str) -> Self:
        unit = currency if isinstance(currency, Currency) else Currency(currency)
        return cls(_decimal(value, field="amount"), unit)

    @classmethod
    def rounded(
        cls,
        value: Decimal | int | str,
        currency: Currency | str,
        policy: RoundingPolicy,
    ) -> Self:
        unit = currency if isinstance(currency, Currency) else Currency(currency)
        return cls(policy.round(value, unit), unit)

    def _same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            from financial_analytics_domain.errors import CurrencyMismatchError

            raise CurrencyMismatchError(
                f"cannot combine {self.currency.code} and {other.currency.code}"
            )

    def __add__(self, other: Money) -> Money:
        self._same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def is_positive(self) -> bool:
        return self.amount > 0


@dataclass(frozen=True, slots=True)
class Rate:
    """An exact dimensionless rate with at most twelve fractional digits."""

    value: Decimal

    SCALE = 12

    def __post_init__(self) -> None:
        exact = _decimal(self.value, field="rate")
        quantum = Decimal(1).scaleb(-self.SCALE)
        with localcontext() as context:
            context.prec = max(64, len(exact.as_tuple().digits) + self.SCALE + 1)
            quantized = exact.quantize(quantum)
        if exact != quantized:
            raise PrecisionError(f"rate permits at most {self.SCALE} fractional digits")
        object.__setattr__(self, "value", exact)

    @classmethod
    def of(cls, value: Decimal | int | str) -> Self:
        return cls(_decimal(value, field="rate"))

    def apply(self, money: Money, policy: RoundingPolicy) -> Money:
        with localcontext() as context:
            context.prec = Money.STORAGE_PRECISION + self.SCALE
            result = money.amount * self.value
        return Money.rounded(result, money.currency, policy)


@dataclass(frozen=True, slots=True)
class DateRange:
    """A half-open calendar date range: ``start <= date < end``."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if isinstance(self.start, datetime) or isinstance(self.end, datetime):
            raise TypeError("date range boundaries must be dates, not datetimes")
        if self.start >= self.end:
            raise ValueError("date range end must be after start")

    def contains(self, value: date) -> bool:
        return self.start <= value < self.end


@dataclass(frozen=True, slots=True)
class Instant:
    """A timezone-aware instant normalized to UTC."""

    value: datetime

    def __post_init__(self) -> None:
        if self.value.tzinfo is None or self.value.utcoffset() is None:
            raise ValueError("instant must be timezone-aware")
        object.__setattr__(self, "value", self.value.astimezone(UTC))

    @classmethod
    def now(cls) -> Self:
        return cls(datetime.now(UTC))

    @classmethod
    def from_datetime(cls, value: datetime) -> Self:
        return cls(value)
