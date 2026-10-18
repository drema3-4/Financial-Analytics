from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from financial_analytics_api.main import create_app
from financial_analytics_app.deposits import DepositService
from financial_analytics_app.forecast import ForecastService
from financial_analytics_app.identity import AuthService
from financial_analytics_app.ledger import LedgerService
from financial_analytics_app.scheduling import SchedulingService
from financial_analytics_domain import Instant
from financial_analytics_infra.models import AuditEventModel, TransactionModel
from financial_analytics_infra.repositories import PostgresUnitOfWorkFactory
from financial_analytics_infra.scheduling import PostgresSchedulingRepository
from financial_analytics_infra.settings import AppEnvironment, Settings
from tests.integration.test_ledger_api import (
    StubApiAuth,
    _client,
    _insert_owners,
    _mutation_headers,
    _profile,
)

pytestmark = pytest.mark.integration
NOW = datetime(2026, 1, 15, 9, tzinfo=UTC)


def _make_app(engine: Engine, owners: dict[str, UUID]) -> object:
    auth = StubApiAuth(
        {token: _profile(owner_id, f"{token}@example.test") for token, owner_id in owners.items()}
    )
    factory = PostgresUnitOfWorkFactory(engine)

    async def ready() -> bool:
        return True

    return create_app(
        settings=Settings(app_env=AppEnvironment.TEST, _env_file=None),
        readiness_check=ready,
        auth_service=cast(AuthService, auth),
        ledger_service=LedgerService(factory),
        scheduling_service=SchedulingService(
            PostgresSchedulingRepository(engine), clock=lambda: Instant(NOW)
        ),
        deposit_service=DepositService(factory, clock=lambda: Instant(NOW)),
        forecast_service=ForecastService(factory, clock=lambda: Instant(NOW)),
    )


def _post(
    client: TestClient,
    owner_id: UUID,
    path: str,
    payload: dict[str, object],
    key: str,
) -> dict[str, object]:
    response = client.post(path, json=payload, headers=_mutation_headers(owner_id, key))
    assert response.status_code == 201, response.text
    return cast(dict[str, object], response.json())


def test_forecast_scenarios_goals_deposits_and_tenant_isolation(
    postgres_engine: Engine,
) -> None:
    owner_id, other_owner_id = uuid4(), uuid4()
    _insert_owners(postgres_engine, owner_id, other_owner_id)
    app = _make_app(postgres_engine, {"owner": owner_id, "other": other_owner_id})
    with (
        _client(app, "owner", owner_id) as client,
        _client(app, "other", other_owner_id) as other,
    ):
        bank = _post(
            client,
            owner_id,
            "/api/v1/accounts",
            {
                "name": "Forecast savings",
                "kind": "bank",
                "currency": "RUB",
                "opening_balance": {"amount": "1000.00", "currency": "RUB"},
                "opening_balance_occurred_at": "2025-09-01T09:00:00+04:00",
            },
            "forecast-bank",
        )
        category = _post(
            client,
            owner_id,
            "/api/v1/categories",
            {"name": "Forecast irregular", "kind": "expense"},
            "forecast-category",
        )
        income_category = _post(
            client,
            owner_id,
            "/api/v1/categories",
            {"name": "Forecast income", "kind": "income"},
            "forecast-income-category",
        )
        for index, (occurred_at, amount) in enumerate(
            (
                ("2025-10-10T09:00:00+04:00", "10.00"),
                ("2025-11-10T09:00:00+04:00", "20.00"),
                ("2025-12-10T09:00:00+04:00", "30.00"),
            )
        ):
            _post(
                client,
                owner_id,
                "/api/v1/transactions/expense",
                {
                    "account_id": bank["id"],
                    "category_id": category["id"],
                    "money": {"amount": amount, "currency": "RUB"},
                    "occurred_at": occurred_at,
                    "description": "Historical irregular expense",
                },
                f"forecast-expense-{index}",
            )

        recurring = client.post(
            "/api/v1/recurring-rules",
            json={
                "frequency": "monthly",
                "starts_on": "2026-01-20",
                "local_time": "09:00:00",
                "timezone": "Europe/Saratov",
                "missing_day_policy": "last_day",
                "catch_up_policy": "all",
                "end_date": "2026-03-20",
                "operation": {
                    "kind": "income",
                    "account_id": bank["id"],
                    "category_id": income_category["id"],
                    "money": {"amount": "100.00", "currency": "RUB"},
                    "description": "Forecast salary",
                },
            },
            headers={"X-CSRF-Token": f"csrf-{owner_id}"},
        )
        assert recurring.status_code == 201, recurring.text

        deposit = _post(
            client,
            owner_id,
            "/api/v1/deposits",
            {
                "name": "Forecast deposit",
                "opening_balance": {"amount": "100.00", "currency": "RUB"},
                "currency": "RUB",
                "opened_on": "2026-01-01",
                "matures_on": "2026-03-31",
                "rate_periods": [
                    {
                        "starts_on": "2026-01-01",
                        "ends_on": "2026-03-31",
                        "nominal_rate": {"value": "0.365"},
                    }
                ],
                "capitalization_frequency": "monthly_calendar_end",
                "day_count_convention": "actual_365_fixed",
                "rounding_policy": "half_even",
                "interest_rounding_frequency": "capitalization",
                "timezone": "UTC",
                "cashflow_cutoff_time": "12:00:00",
                "cashflow_cutoff_inclusive": True,
                "early_close_rule": {"policy": "forbid", "nominal_rate": None},
                "tax_rate": {"value": "0"},
            },
            "forecast-deposit",
        )
        assert deposit["name"] == "Forecast deposit"

        scenario_payload: dict[str, object] = {
            "name": "Higher income",
            "currency": "RUB",
            "horizon": "2026-03-31",
            "income_change": {"value": "0.10"},
            "expense_change": {"value": "0"},
            "annual_inflation": {"value": "0.12"},
            "annual_interest": {"value": "0.06"},
            "one_time_cashflows": [
                {
                    "occurs_on": "2026-02-10",
                    "account_id": bank["id"],
                    "money": {"amount": "50.00", "currency": "RUB"},
                    "description": "Refund",
                }
            ],
        }
        scenario = _post(
            client,
            owner_id,
            "/api/v1/forecast-scenarios",
            scenario_payload,
            "forecast-scenario",
        )
        replay = client.post(
            "/api/v1/forecast-scenarios",
            json=scenario_payload,
            headers=_mutation_headers(owner_id, "forecast-scenario"),
        )
        assert replay.status_code == 201 and replay.json()["id"] == scenario["id"]
        second = _post(
            client,
            owner_id,
            "/api/v1/forecast-scenarios",
            {
                **scenario_payload,
                "name": "Control scenario",
                "income_change": {"value": "0"},
                "one_time_cashflows": [],
            },
            "forecast-scenario-control",
        )
        updated = client.put(
            f"/api/v1/forecast-scenarios/{scenario['id']}",
            json={**scenario_payload, "name": "Higher income updated", "version": 1},
            headers=_mutation_headers(owner_id, "unused-update-key"),
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["version"] == 2
        assert client.get(f"/api/v1/forecast-scenarios/{second['id']}").json()["name"] == (
            "Control scenario"
        )

        goal = _post(
            client,
            owner_id,
            "/api/v1/goals",
            {
                "name": "Emergency fund",
                "target": {"amount": "500.00", "currency": "RUB"},
                "target_date": "2026-03-31",
                "saved_amount": {"amount": "100.00", "currency": "RUB"},
                "priority": 1,
                "linked_account_id": bank["id"],
            },
            "forecast-goal",
        )
        assert other.get(f"/api/v1/goals/{goal['id']}").status_code == 404
        assert other.get(f"/api/v1/forecast-scenarios/{scenario['id']}").status_code == 404
        assert other.get("/api/v1/goals").json() == []

        with Session(postgres_engine) as session:
            ledger_count_before = session.scalar(
                select(func.count())
                .select_from(TransactionModel)
                .where(TransactionModel.owner_id == owner_id)
            )

        baseline = client.get(
            "/api/v1/forecasts",
            params={"currency": "RUB", "through": "2026-03-31"},
        )
        assert baseline.status_code == 200, baseline.text
        baseline_body = baseline.json()
        assert baseline_body["forecast"]["algorithm_version"] == "monthly-cashflow-v1"
        assert baseline_body["forecast"]["baseline_expenses"][0]["sample_count"] == 3
        assert baseline_body["forecast"]["timeline"][-1]["deposit_interest"]["amount"] != "0.00"
        assert baseline_body["goal_plan"]["goals"][0]["required_monthly_contribution"] == {
            "amount": "133.34",
            "currency": "RUB",
        }

        scenario_result = client.get(
            "/api/v1/forecasts",
            params={"currency": "RUB", "scenario_id": str(scenario["id"])},
        )
        assert scenario_result.status_code == 200, scenario_result.text
        assert Decimal(scenario_result.json()["forecast"]["final_total"]["amount"]) > Decimal(
            baseline_body["forecast"]["final_total"]["amount"]
        )
        compare = client.post(
            "/api/v1/forecasts/compare",
            json={
                "currency": "RUB",
                "baseline_horizon": "2026-03-31",
                "scenario_ids": [scenario["id"], second["id"]],
            },
        )
        assert compare.status_code == 200, compare.text
        compared = compare.json()
        assert len(compared["items"]) == 3
        assert {item["forecast"]["snapshot_id"] for item in compared["items"]} == {
            compared["snapshot_id"]
        }

        with Session(postgres_engine) as session:
            ledger_count_after = session.scalar(
                select(func.count())
                .select_from(TransactionModel)
                .where(TransactionModel.owner_id == owner_id)
            )
            audit_types = set(
                session.scalars(
                    select(AuditEventModel.event_type).where(AuditEventModel.owner_id == owner_id)
                )
            )
        assert ledger_count_after == ledger_count_before
        assert {
            "forecast.scenario_created",
            "forecast.scenario_updated",
            "goal.created",
        }.issubset(audit_types)
        paused = client.post(
            f"/api/v1/recurring-rules/{recurring.json()['id']}/pause",
            json={"version": recurring.json()["version"]},
            headers={"X-CSRF-Token": f"csrf-{owner_id}"},
        )
        assert paused.status_code == 200, paused.text
