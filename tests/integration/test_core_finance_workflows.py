from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from financial_analytics_api.main import create_app
from financial_analytics_app.analytics import AnalyticsService
from financial_analytics_app.deposits import DepositService
from financial_analytics_app.forecast import ForecastService
from financial_analytics_app.identity import AuthService
from financial_analytics_app.ledger import LedgerService
from financial_analytics_domain import Instant
from financial_analytics_infra.deposits import DepositAccrualProcessor
from financial_analytics_infra.models import AuditEventModel, TransactionModel
from financial_analytics_infra.repositories import PostgresUnitOfWorkFactory
from financial_analytics_infra.settings import AppEnvironment, Settings
from tests.integration.test_ledger_api import (
    StubApiAuth,
    _client,
    _insert_owners,
    _mutation_headers,
    _profile,
)

pytestmark = pytest.mark.integration
NOW = datetime(2026, 2, 2, 9, tzinfo=UTC)


def make_app(engine: Engine, owners: dict[str, UUID], now: datetime = NOW) -> object:
    factory = PostgresUnitOfWorkFactory(engine)
    auth = StubApiAuth(
        {token: _profile(owner, f"{token}@example.test") for token, owner in owners.items()}
    )

    async def ready() -> bool:
        return True

    return create_app(
        settings=Settings(app_env=AppEnvironment.TEST, _env_file=None),
        readiness_check=ready,
        auth_service=cast(AuthService, auth),
        ledger_service=LedgerService(factory, clock=lambda: Instant(now)),
        deposit_service=DepositService(factory, clock=lambda: Instant(now)),
        analytics_service=AnalyticsService(factory, clock=lambda: Instant(now)),
        forecast_service=ForecastService(factory, clock=lambda: Instant(now)),
    )


def deposit_input(opening: str = "1000.00", rate: str = "0.365") -> dict[str, Any]:
    return {
        "name": "Резерв",
        "opening_balance": {"amount": opening, "currency": "RUB"},
        "currency": "RUB",
        "opened_on": "2026-01-01",
        "matures_on": "2026-03-01",
        "rate_periods": [
            {"starts_on": "2026-01-01", "ends_on": "2026-03-01", "nominal_rate": {"value": rate}}
        ],
        "capitalization_frequency": "monthly_calendar_end",
        "day_count_convention": "actual_365_fixed",
        "rounding_policy": "half_even",
        "interest_rounding_frequency": "capitalization",
        "timezone": "UTC",
        "cashflow_cutoff_time": "23:59:59",
        "cashflow_cutoff_inclusive": True,
        "early_close_rule": {"policy": "forfeit_interest", "nominal_rate": None},
        "tax_rate": {"value": "0"},
    }


def post(
    client: TestClient, owner: UUID, path: str, data: dict[str, Any], key: str | None = None
) -> dict[str, Any]:
    response = client.post(path, json=data, headers=_mutation_headers(owner, key or str(uuid4())))
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def count_transactions(engine: Engine, owner: UUID) -> int:
    with Session(engine) as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(TransactionModel)
                .where(TransactionModel.owner_id == owner)
            )
            or 0
        )


def test_standalone_deposit_compounds_posts_once_and_reconciles_all_views(
    postgres_engine: Engine,
) -> None:
    owner = uuid4()
    _insert_owners(postgres_engine, owner)
    with _client(make_app(postgres_engine, {"owner": owner}), "owner", owner) as client:
        deposit = post(client, owner, "/api/v1/deposits", deposit_input(), "standalone")
        assert client.get("/api/v1/accounts").json() == []
        assert client.get("/api/v1/deposits").json() == [deposit]
        value = client.get(
            f"/api/v1/deposits/{deposit['id']}/valuation", params={"as_of": "2026-02-02"}
        ).json()
        assert value["ledger_balance"]["amount"] == "1031.00"
        assert value["current_value"]["amount"] == "1032.03"
        assert value["earned_interest"]["amount"] == "32.03"
        assert value["projected_maturity_value"]["amount"] == "1059.87"
        assert value["schedule"][1]["opening_balance"]["amount"] == "1031.00"
        assert value["reconciliation"][0]["actual_interest"]["amount"] == "31.00"
        before = count_transactions(postgres_engine, owner)
        processor = DepositAccrualProcessor(postgres_engine, clock=lambda: Instant(NOW))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(processor.tick, ["first", "second"]))
        assert all(result.failed == 0 for result in results)
        assert count_transactions(postgres_engine, owner) == before
        replay = post(client, owner, "/api/v1/deposits", deposit_input(), "standalone")
        assert replay["id"] == deposit["id"]
        assert count_transactions(postgres_engine, owner) == before

        report = client.get(
            "/api/v1/reports/financial",
            params={
                "period_start": "2026-02-01",
                "period_end": "2026-03-01",
                "granularity": "month",
            },
        )
        assert report.status_code == 200, report.text
        assert report.json()["totals"][0]["income"]["value"]["amount"] == "31.00"
        assert report.json()["totals"][0]["closing_net_worth"]["value"]["amount"] == "1031.00"
        forecast = client.get(
            "/api/v1/forecasts", params={"currency": "RUB", "through": "2026-03-01"}
        )
        assert forecast.status_code == 200, forecast.text
        assert forecast.json()["forecast"]["opening_total"]["amount"] == "1031.00"
        assert forecast.json()["forecast"]["final_total"]["amount"] == "1059.87"


def test_opening_day_nonzero_and_empty_deposit_can_receive_a_transfer(
    postgres_engine: Engine,
) -> None:
    owner = uuid4()
    _insert_owners(postgres_engine, owner)
    now = datetime(2026, 1, 1, 16, tzinfo=UTC)
    with _client(make_app(postgres_engine, {"owner": owner}, now), "owner", owner) as client:
        initial = post(client, owner, "/api/v1/deposits", deposit_input())
        value = client.get(
            f"/api/v1/deposits/{initial['id']}/valuation", params={"as_of": "2026-01-01"}
        ).json()
        assert value["current_value"]["amount"] == "1000.00"
        assert value["earned_interest"]["amount"] == "0.00"
        bank = post(
            client,
            owner,
            "/api/v1/accounts",
            {
                "name": "Карта",
                "kind": "bank",
                "currency": "RUB",
                "opening_balance": {"amount": "1000", "currency": "RUB"},
                "opening_balance_occurred_at": "2026-01-01T08:00:00Z",
            },
        )
        empty = post(client, owner, "/api/v1/deposits", deposit_input("0"))
        post(
            client,
            owner,
            "/api/v1/transfers",
            {
                "source_account_id": bank["id"],
                "destination_account_id": empty["principal_account_id"],
                "money": {"amount": "100", "currency": "RUB"},
                "occurred_at": "2026-01-01T12:00:00Z",
            },
        )
        assert client.get(f"/api/v1/accounts/{bank['id']}").json()["balance"]["amount"] == "900.00"
        value = client.get(
            f"/api/v1/deposits/{empty['id']}/valuation", params={"as_of": "2026-01-01"}
        ).json()
        assert value["current_value"]["amount"] == "100.00"
        assert value["projected_maturity_value"]["amount"] == "105.99"


def test_operations_edit_delete_transfer_deposit_to_deposit_and_reject_overdraft_atomically(
    postgres_engine: Engine,
) -> None:
    owner, other = uuid4(), uuid4()
    _insert_owners(postgres_engine, owner, other)
    app = make_app(postgres_engine, {"owner": owner, "other": other})
    with _client(app, "owner", owner) as client, _client(app, "other", other) as stranger:
        first = post(client, owner, "/api/v1/deposits", deposit_input())
        second = post(client, owner, "/api/v1/deposits", deposit_input("0"))
        category = post(
            client, owner, "/api/v1/categories", {"name": "Продукты", "kind": "expense"}
        )
        expense = post(
            client,
            owner,
            "/api/v1/transactions/expense",
            {
                "account_id": first["principal_account_id"],
                "category_id": category["id"],
                "money": {"amount": "10", "currency": "RUB"},
                "occurred_at": "2026-01-16T08:00:00Z",
                "description": "Продукты",
            },
        )
        before = count_transactions(postgres_engine, owner)
        correction = {
            "kind": "expense",
            "account_id": first["principal_account_id"],
            "category_id": category["id"],
            "money": {"amount": "20", "currency": "RUB"},
            "occurred_at": "2026-01-16T08:00:00Z",
            "description": "Исправленные продукты",
            "reason": "Чек уточнён",
        }
        assert (
            stranger.post(
                f"/api/v1/transactions/{expense['id']}/correction",
                json=correction,
                headers=_mutation_headers(other, "idor"),
            ).status_code
            == 404
        )
        bad = client.post(
            f"/api/v1/transactions/{expense['id']}/correction",
            json={**correction, "money": {"amount": "10000", "currency": "RUB"}},
            headers=_mutation_headers(owner, "bad"),
        )
        assert bad.status_code == 422, bad.text
        assert count_transactions(postgres_engine, owner) == before
        assert client.get(f"/api/v1/transactions/{expense['id']}").json()["reversed_by_id"] is None
        corrected = post(
            client,
            owner,
            f"/api/v1/transactions/{expense['id']}/correction",
            correction,
            "correction",
        )
        count = count_transactions(postgres_engine, owner)
        assert (
            post(
                client,
                owner,
                f"/api/v1/transactions/{expense['id']}/correction",
                correction,
                "correction",
            )["id"]
            == corrected["id"]
        )
        assert count_transactions(postgres_engine, owner) == count
        assert (
            client.get(f"/api/v1/transactions/{expense['id']}").json()["reversed_by_id"] is not None
        )
        post(
            client,
            owner,
            f"/api/v1/transactions/{corrected['id']}/reversal",
            {"occurred_at": corrected["occurred_at"], "reason": "Удалено"},
        )
        value = client.get(
            f"/api/v1/deposits/{first['id']}/valuation", params={"as_of": "2026-02-02"}
        ).json()
        assert value["ledger_balance"]["amount"] == "1031.00"
        transfer = post(
            client,
            owner,
            "/api/v1/transfers",
            {
                "source_account_id": first["principal_account_id"],
                "destination_account_id": second["principal_account_id"],
                "money": {"amount": "100", "currency": "RUB"},
                "occurred_at": "2026-02-01T08:00:00Z",
            },
        )
        assert sum(Decimal(p["money"]["amount"]) for p in transfer["postings"]) == 0
        for deposit, expected in ((first, "931.00"), (second, "100.00")):
            value = client.get(
                f"/api/v1/deposits/{deposit['id']}/valuation", params={"as_of": "2026-02-02"}
            ).json()
            assert value["ledger_balance"]["amount"] == expected


def test_update_archive_accounts_deposits_goals_versions_audit_and_cross_tenant(
    postgres_engine: Engine,
) -> None:
    owner, other = uuid4(), uuid4()
    _insert_owners(postgres_engine, owner, other)
    app = make_app(postgres_engine, {"owner": owner, "other": other})
    with _client(app, "owner", owner) as client, _client(app, "other", other) as stranger:
        bank = post(
            client, owner, "/api/v1/accounts", {"name": "Карта", "kind": "bank", "currency": "RUB"}
        )
        updated = client.patch(
            f"/api/v1/accounts/{bank['id']}",
            json={
                "version": 1,
                "name": "Наличные",
                "kind": "cash",
                "balance": {"amount": "500", "currency": "RUB"},
            },
            headers=_mutation_headers(owner, "update"),
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["balance"]["amount"] == "500.00"
        assert updated.json()["kind"] == "cash"
        deposit = post(client, owner, "/api/v1/deposits", deposit_input())
        terms = deposit_input(rate="0.73")
        terms.pop("opening_balance")
        terms.update({"name": "Обновлённый резерв", "version": 1})
        assert (
            stranger.put(
                f"/api/v1/deposits/{deposit['id']}",
                json=terms,
                headers=_mutation_headers(other, "idor-update"),
            ).status_code
            == 404
        )
        updated = client.put(
            f"/api/v1/deposits/{deposit['id']}",
            json=terms,
            headers=_mutation_headers(owner, "update-deposit"),
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["version"] == 2
        assert (
            client.put(
                f"/api/v1/deposits/{deposit['id']}",
                json=terms,
                headers=_mutation_headers(owner, "stale"),
            ).status_code
            == 409
        )
        value = client.get(
            f"/api/v1/deposits/{deposit['id']}/valuation", params={"as_of": "2026-02-02"}
        ).json()
        assert value["ledger_balance"]["amount"] == "1062.00"
        goal_input = {
            "name": "Резерв",
            "target": {"amount": "5000", "currency": "RUB"},
            "saved_amount": {"amount": "500", "currency": "RUB"},
            "target_date": "2026-12-31",
            "priority": 1,
            "linked_account_id": bank["id"],
        }
        goal = post(client, owner, "/api/v1/goals", goal_input)
        updated = client.put(
            f"/api/v1/goals/{goal['id']}",
            json={**goal_input, "name": "На ремонт", "version": 1},
            headers=_mutation_headers(owner, "goal-update"),
        )
        assert updated.status_code == 200, updated.text
        for path, version in (
            (f"/api/v1/deposits/{deposit['id']}", 2),
            (f"/api/v1/goals/{goal['id']}", 2),
        ):
            assert (
                stranger.request(
                    "DELETE",
                    path,
                    json={"version": version},
                    headers=_mutation_headers(other, "idor-delete"),
                ).status_code
                == 404
            )
            deleted = client.request(
                "DELETE",
                path,
                json={"version": version},
                headers=_mutation_headers(owner, "delete"),
            )
            assert deleted.status_code == 200, deleted.text
            assert deleted.json()["archived"] is True
            assert client.get(path).status_code == 404
        assert client.get("/api/v1/deposits").json() == []
        assert client.get("/api/v1/goals").json() == []
        archived = client.patch(
            f"/api/v1/accounts/{bank['id']}",
            json={"version": 2, "archived": True},
            headers=_mutation_headers(owner, "archive-bank"),
        )
        assert archived.status_code == 200, archived.text
        assert client.get("/api/v1/accounts").json() == []
    with Session(postgres_engine) as session:
        events = session.scalars(
            select(AuditEventModel).where(AuditEventModel.owner_id == owner)
        ).all()
        assert {
            "deposit.terms_updated",
            "deposit.archived",
            "goal.updated",
            "goal.archived",
            "ledger.account_updated",
        } <= {e.event_type for e in events}
        changed = next(e for e in events if e.event_type == "deposit.terms_updated")
        assert changed.payload is not None
        before_snapshot = cast(dict[str, Any], changed.payload["before"])
        after_snapshot = cast(dict[str, Any], changed.payload["after"])
        assert before_snapshot["rates"][0]["nominal_rate"] == "0.365000000000"
        assert after_snapshot["rates"][0]["nominal_rate"] == "0.730000000000"
