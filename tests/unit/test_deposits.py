from __future__ import annotations

import csv
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, localcontext
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from financial_analytics_domain import (
    DEPOSIT_ALGORITHM_VERSION,
    CapitalizationFrequency,
    Currency,
    DayCountConvention,
    DepositCashflow,
    DepositRatePeriod,
    DepositTerms,
    EarlyClosePolicy,
    EarlyCloseRule,
    Instant,
    InterestRoundingFrequency,
    Money,
    Rate,
    RoundingPolicy,
    day_count_fraction,
    effective_cashflow_date,
    project_deposit,
)
from financial_analytics_domain.errors import DomainError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "deposits"
OWNER = UUID("00000000-0000-0000-0000-000000000001")
ACCOUNT = UUID("00000000-0000-0000-0000-000000000002")


def _rows(name: str) -> list[dict[str, str]]:
    with (FIXTURES / name).open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def _fixture_cases() -> dict[str, tuple[DepositTerms, tuple[DepositCashflow, ...], dict[str, str]]]:
    rate_rows: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    flow_rows: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    for row in _rows("rate_periods.csv"):
        rate_rows[row["case"]].append(row)
    for row in _rows("cashflows.csv"):
        flow_rows[row["case"]].append(row)
    result: dict[str, tuple[DepositTerms, tuple[DepositCashflow, ...], dict[str, str]]] = {}
    for row in _rows("terms.csv"):
        case = row["case"]
        early_rate = row["early_rate"]
        terms = DepositTerms(
            id=uuid5(NAMESPACE_URL, f"deposit:{case}"),
            owner_id=OWNER,
            principal_account_id=ACCOUNT,
            currency=Currency("USD"),
            opened_on=date.fromisoformat(row["opened_on"]),
            matures_on=date.fromisoformat(row["matures_on"]),
            rate_periods=tuple(
                DepositRatePeriod(
                    date.fromisoformat(rate["starts_on"]),
                    date.fromisoformat(rate["ends_on"]),
                    Rate.of(rate["nominal_rate"]),
                )
                for rate in rate_rows[case]
            ),
            capitalization_frequency=CapitalizationFrequency(row["capitalization"]),
            day_count_convention=DayCountConvention(row["day_count"]),
            rounding_policy=RoundingPolicy(row["rounding"]),
            interest_rounding_frequency=InterestRoundingFrequency(row["rounding_frequency"]),
            timezone=row["timezone"],
            cashflow_cutoff_time=time.fromisoformat(row["cutoff"]),
            cashflow_cutoff_inclusive=row["cutoff_inclusive"] == "true",
            early_close_rule=EarlyCloseRule(
                EarlyClosePolicy(row["early_policy"]),
                None if not early_rate else Rate.of(early_rate),
            ),
            tax_rate=Rate.of(row["tax_rate"]),
        )
        cashflows = tuple(
            DepositCashflow(
                uuid5(NAMESPACE_URL, f"{case}:{index}"),
                Instant(datetime.fromisoformat(flow["occurred_at"])),
                Money.of(flow["amount"], "USD"),
            )
            for index, flow in enumerate(flow_rows[case])
        )
        result[case] = (terms, cashflows, row)
    return result


def test_independent_tabular_fixtures_match_schedule_and_summary() -> None:
    cases = _fixture_cases()
    expected: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    for row in _rows("expected_schedule.csv"):
        expected[row["case"]].append(row)

    for case, (terms, cashflows, summary) in cases.items():
        close_on = date.fromisoformat(summary["close_on"]) if summary["close_on"] else None
        projection = project_deposit(
            terms,
            cashflows,
            as_of=date.fromisoformat(summary["as_of"]),
            close_on=close_on,
        )
        assert projection.algorithm_version == DEPOSIT_ALGORITHM_VERSION
        assert (
            projection.current_principal.amount
            == Money.of(summary["expected_current_principal"], "USD").amount
        )
        assert (
            projection.accrued_interest.amount
            == Money.of(summary["expected_accrued_interest"], "USD").amount
        )
        assert (
            projection.current_value.amount
            == Money.of(summary["expected_current_value"], "USD").amount
        )
        assert (
            projection.projected_closing_value.amount
            == Money.of(summary["expected_closing_value"], "USD").amount
        )
        assert len(projection.schedule) == len(expected[case])
        for actual, reference in zip(projection.schedule, expected[case], strict=True):
            assert actual.accrual_starts_on == date.fromisoformat(reference["accrual_starts_on"])
            assert actual.accrual_ends_on == date.fromisoformat(reference["accrual_ends_on"])
            for field in (
                "opening_balance",
                "cashflow",
                "gross_interest",
                "tax",
                "net_interest",
                "closing_balance",
            ):
                assert getattr(actual, field).amount == Money.of(reference[field], "USD").amount


def test_cutoff_is_explicit_on_both_sides_and_at_boundary() -> None:
    terms, _, _ = _fixture_cases()["cutoff_boundary"]

    def cashflow(at: str) -> DepositCashflow:
        return DepositCashflow(
            uuid5(NAMESPACE_URL, at),
            Instant(datetime.fromisoformat(at)),
            Money.of("1.00", "USD"),
        )

    assert effective_cashflow_date(terms, cashflow("2024-01-02T11:59:00+00:00")) == date(2024, 1, 2)
    assert effective_cashflow_date(terms, cashflow("2024-01-02T12:00:00+00:00")) == date(2024, 1, 2)
    assert effective_cashflow_date(terms, cashflow("2024-01-02T12:01:00+00:00")) == date(2024, 1, 3)


def test_day_count_and_early_close_rules_cover_boundaries() -> None:
    with localcontext() as context:
        context.prec = 64
        expected = Decimal(1) / Decimal(365) + Decimal(1) / Decimal(366)
    assert (
        day_count_fraction(
            date(2023, 12, 31), date(2024, 1, 2), DayCountConvention.ACTUAL_ACTUAL_ISDA
        )
        == expected
    )
    terms, cashflows, _ = _fixture_cases()["early_close"]
    forbidden = DepositTerms(
        **{
            field: getattr(terms, field)
            for field in terms.__dataclass_fields__
            if field != "early_close_rule"
        },
        early_close_rule=EarlyCloseRule(EarlyClosePolicy.FORBID, None),
    )
    with pytest.raises(DomainError, match="forbid"):
        project_deposit(forbidden, cashflows, as_of=date(2024, 1, 6), close_on=date(2024, 1, 6))


@settings(max_examples=24, deadline=None)
@given(
    principal=st.integers(min_value=1, max_value=100_000),
    basis_points=st.integers(min_value=0, max_value=5_000),
    days=st.integers(min_value=1, max_value=60),
)
def test_projection_is_deterministic_and_never_uses_binary_float(
    principal: int, basis_points: int, days: int
) -> None:
    opened = date(2024, 1, 1)
    maturity = opened + timedelta(days=days)
    rate = Rate.of(str(basis_points).rjust(5, "0")[:-4] + "." + str(basis_points).rjust(4, "0"))
    terms = DepositTerms(
        id=uuid5(NAMESPACE_URL, f"property:{principal}:{basis_points}:{days}"),
        owner_id=OWNER,
        principal_account_id=ACCOUNT,
        currency=Currency("USD"),
        opened_on=opened,
        matures_on=maturity,
        rate_periods=(DepositRatePeriod(opened, maturity, rate),),
        capitalization_frequency=CapitalizationFrequency.DAILY,
        day_count_convention=DayCountConvention.ACTUAL_365_FIXED,
        rounding_policy=RoundingPolicy.HALF_EVEN,
        interest_rounding_frequency=InterestRoundingFrequency.DAILY,
        timezone="UTC",
        cashflow_cutoff_time=time(12),
        cashflow_cutoff_inclusive=False,
        early_close_rule=EarlyCloseRule(EarlyClosePolicy.FORFEIT_INTEREST, None),
        tax_rate=Rate.of("0"),
    )
    flow = DepositCashflow(
        uuid5(NAMESPACE_URL, "property-flow"),
        Instant(datetime(2024, 1, 1, 9, tzinfo=UTC)),
        Money.of(f"{principal}.00", "USD"),
    )
    first = project_deposit(terms, (flow,), as_of=maturity)
    second = project_deposit(terms, (flow,), as_of=maturity)
    assert first == second
    assert first.projected_closing_value.amount >= flow.amount.amount
    assert first.effective_yield is not None


def test_invalid_terms_cashflows_and_rate_coverage_are_rejected() -> None:
    terms, cashflows, _ = _fixture_cases()["monthly_tax"]
    with pytest.raises(DomainError, match="without gaps"):
        DepositTerms(
            **{
                field: getattr(terms, field)
                for field in terms.__dataclass_fields__
                if field != "rate_periods"
            },
            rate_periods=(DepositRatePeriod(date(2024, 1, 2), date(2024, 3, 1), Rate.of("0.12")),),
        )
    with pytest.raises(DomainError, match="outside"):
        project_deposit(
            terms,
            (
                DepositCashflow(
                    uuid5(NAMESPACE_URL, "late"),
                    Instant(datetime(2024, 3, 2, 9, tzinfo=UTC)),
                    Money.of("1.00", "USD"),
                ),
            ),
            as_of=terms.matures_on,
        )
    with pytest.raises(DomainError, match="exceeds"):
        project_deposit(
            terms,
            (
                cashflows[0],
                DepositCashflow(
                    uuid5(NAMESPACE_URL, "overdraw"),
                    Instant(datetime(2024, 1, 2, 9, tzinfo=UTC)),
                    Money.of("-2000.00", "USD"),
                ),
            ),
            as_of=terms.matures_on,
        )
