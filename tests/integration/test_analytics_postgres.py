from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, text

from financial_analytics_api.main import create_app
from financial_analytics_app.analytics import AnalyticsService
from financial_analytics_app.identity import AuthService
from financial_analytics_app.ledger import LedgerService
from financial_analytics_domain import AnalyticsPeriod, Instant, PeriodGranularity
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
NOW = datetime(2026, 11, 2, 9, tzinfo=UTC)


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
        analytics_service=AnalyticsService(factory, clock=lambda: Instant(NOW)),
    )


def _account(
    client: TestClient,
    owner_id: UUID,
    *,
    name: str,
    currency: str,
    key: str,
) -> dict[str, object]:
    response = client.post(
        "/api/v1/accounts",
        json={"name": name, "kind": "bank", "currency": currency},
        headers=_mutation_headers(owner_id, key),
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, object], response.json())


def _operation(
    client: TestClient,
    owner_id: UUID,
    *,
    kind: str,
    account_id: object,
    category_id: object,
    amount: str,
    currency: str,
    key: str,
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/transactions/{kind}",
        json={
            "account_id": account_id,
            "category_id": category_id,
            "money": {"amount": amount, "currency": currency},
            "occurred_at": "2026-10-10T12:00:00+04:00",
            "description": key,
        },
        headers=_mutation_headers(owner_id, key),
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, object], response.json())


def test_reports_reconcile_mixed_currency_reversals_transfers_and_tenant_scope(
    postgres_engine: Engine,
) -> None:
    owner_id, other_owner_id = uuid4(), uuid4()
    _insert_owners(postgres_engine, owner_id, other_owner_id)
    app = _make_app(postgres_engine, {"owner": owner_id, "other": other_owner_id})
    with (
        _client(app, "owner", owner_id) as client,
        _client(app, "other", other_owner_id) as other,
    ):
        rub_bank = _account(
            client, owner_id, name="RUB Bank", currency="RUB", key="analytics-rub-bank"
        )
        rub_cash = _account(
            client, owner_id, name="RUB Cash", currency="RUB", key="analytics-rub-cash"
        )
        usd_bank = _account(
            client, owner_id, name="USD Bank", currency="USD", key="analytics-usd-bank"
        )
        group = client.post(
            "/api/v1/category-groups",
            json={"name": "Analytics household"},
            headers=_mutation_headers(owner_id, "analytics-group"),
        ).json()
        salary = client.post(
            "/api/v1/categories",
            json={
                "name": "Analytics salary",
                "kind": "income",
                "group_id": group["id"],
            },
            headers=_mutation_headers(owner_id, "analytics-salary"),
        ).json()
        rent = client.post(
            "/api/v1/categories",
            json={
                "name": "Analytics rent",
                "kind": "expense",
                "group_id": group["id"],
                "is_mandatory": True,
            },
            headers=_mutation_headers(owner_id, "analytics-rent"),
        ).json()
        food = client.post(
            "/api/v1/categories",
            json={
                "name": "Analytics food",
                "kind": "expense",
                "group_id": group["id"],
            },
            headers=_mutation_headers(owner_id, "analytics-food"),
        ).json()
        usd_salary = client.post(
            "/api/v1/categories",
            json={"name": "Analytics USD salary", "kind": "income"},
            headers=_mutation_headers(owner_id, "analytics-usd-salary"),
        ).json()
        assert rent["is_mandatory"] is True

        income = _operation(
            client,
            owner_id,
            kind="income",
            account_id=rub_bank["id"],
            category_id=salary["id"],
            amount="1000.00",
            currency="RUB",
            key="analytics-income",
        )
        _operation(
            client,
            owner_id,
            kind="expense",
            account_id=rub_bank["id"],
            category_id=rent["id"],
            amount="300.00",
            currency="RUB",
            key="analytics-rent-expense",
        )
        food_expense = _operation(
            client,
            owner_id,
            kind="expense",
            account_id=rub_bank["id"],
            category_id=food["id"],
            amount="100.00",
            currency="RUB",
            key="analytics-food-expense",
        )
        reversal = client.post(
            f"/api/v1/transactions/{food_expense['id']}/reversal",
            json={"occurred_at": "2026-10-11T12:00:00+04:00", "reason": "Correction"},
            headers=_mutation_headers(owner_id, "analytics-food-reversal"),
        ).json()
        transfer = client.post(
            "/api/v1/transfers",
            json={
                "source_account_id": rub_bank["id"],
                "destination_account_id": rub_cash["id"],
                "money": {"amount": "200.00", "currency": "RUB"},
                "occurred_at": "2026-10-12T12:00:00+04:00",
            },
            headers=_mutation_headers(owner_id, "analytics-transfer"),
        ).json()
        _operation(
            client,
            owner_id,
            kind="income",
            account_id=usd_bank["id"],
            category_id=usd_salary["id"],
            amount="10.00",
            currency="USD",
            key="analytics-usd-income",
        )

        params = {
            "period_start": "2026-10-01",
            "period_end": "2026-11-01",
            "granularity": "month",
        }
        response = client.get("/api/v1/reports/financial", params=params)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["currency_mode"] == "separated_by_currency"
        assert body["combined_currency"] is None
        rub = next(item for item in body["totals"] if item["currency"] == "RUB")
        assert rub["income"]["value"]["amount"] == "1000.00"
        assert rub["expense"]["value"]["amount"] == "300.00"
        assert rub["cash_flow"]["value"]["amount"] == "700.00"
        assert rub["mandatory_expense_share"]["value"] == "1.000000"
        assert sum(
            Decimal(item["amount"]["amount"])
            for item in rub["category_breakdown"]
            if item["flow_type"] == "expense"
        ) == Decimal("300.00")
        cash_flow_ids = set(rub["cash_flow"]["evidence"]["transaction_ids"])
        assert income["id"] in cash_flow_ids
        assert food_expense["id"] in cash_flow_ids
        assert reversal["id"] in cash_flow_ids
        assert transfer["id"] not in cash_flow_ids

        dashboard = client.get("/api/v1/analytics/dashboard", params=params)
        assert dashboard.status_code == 200
        assert dashboard.json()["currency_mode"] == "separated_by_currency"

        foreign = other.get("/api/v1/reports/financial", params=params)
        assert foreign.status_code == 200
        assert foreign.json()["currency_mode"] == "empty"
        assert foreign.json()["totals"] == []
        assert str(income["id"]) not in foreign.text

        invalid = client.get(
            "/api/v1/reports/financial",
            params={
                "period_start": "2026-10-02",
                "period_end": "2026-11-01",
                "granularity": "month",
            },
        )
        assert invalid.status_code == 422


def test_analytics_query_plan_and_statement_count_budget(postgres_engine: Engine) -> None:
    owner_id, noise_owner_id = uuid4(), uuid4()
    _insert_owners(postgres_engine, owner_id, noise_owner_id)
    with postgres_engine.begin() as connection:
        for current_owner, suffix in ((owner_id, "a"), (noise_owner_id, "b")):
            asset_id, expense_id, category_id = uuid4(), uuid4(), uuid4()
            connection.execute(
                text(
                    """
                    INSERT INTO accounts (id, owner_id, name, kind, currency, archived, version)
                    VALUES (:asset, :owner, :asset_name, 'bank', 'RUB', false, 1),
                           (:expense, :owner, :expense_name, 'system_expense', 'RUB', false, 1)
                    """
                ),
                {
                    "asset": asset_id,
                    "expense": expense_id,
                    "owner": current_owner,
                    "asset_name": f"Synthetic asset {suffix}",
                    "expense_name": f"System expense synthetic {suffix}",
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO categories
                        (id, owner_id, name, kind, is_mandatory, version)
                    VALUES (:category, :owner, :category_name, 'expense', true, 1)
                    """
                ),
                {
                    "category": category_id,
                    "owner": current_owner,
                    "category_name": f"Synthetic category {suffix}",
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO transactions
                        (id, owner_id, actor_id, category_id, kind, status, currency,
                         description, source, occurred_at, version)
                    SELECT md5(:owner_text || ':tx:' || value::text)::uuid,
                           :owner, :owner, :category, 'expense', 'pending', 'RUB',
                           'synthetic analytics plan row', 'import',
                           timestamptz '2023-01-01 00:00:00+00'
                               + value * interval '4 hours',
                           1
                    FROM generate_series(1, 5000) AS value
                    """
                ),
                {
                    "owner": current_owner,
                    "owner_text": str(current_owner),
                    "category": category_id,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO postings
                        (id, owner_id, transaction_id, account_id, line_no, currency, amount)
                    SELECT md5(:owner_text || ':asset:' || value::text)::uuid,
                           :owner,
                           md5(:owner_text || ':tx:' || value::text)::uuid,
                           :asset, 1, 'RUB', -1.00
                    FROM generate_series(1, 5000) AS value
                    """
                ),
                {
                    "owner": current_owner,
                    "owner_text": str(current_owner),
                    "asset": asset_id,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO postings
                        (id, owner_id, transaction_id, account_id, line_no, currency, amount)
                    SELECT md5(:owner_text || ':expense:' || value::text)::uuid,
                           :owner,
                           md5(:owner_text || ':tx:' || value::text)::uuid,
                           :expense, 2, 'RUB', 1.00
                    FROM generate_series(1, 5000) AS value
                    """
                ),
                {
                    "owner": current_owner,
                    "owner_text": str(current_owner),
                    "expense": expense_id,
                },
            )
            connection.execute(
                text(
                    """
                    UPDATE transactions SET status = 'posted'
                    WHERE owner_id = :owner AND status = 'pending'
                    """
                ),
                {"owner": current_owner},
            )
        connection.execute(text("ANALYZE transactions"))
        raw_plan: object = connection.execute(
            text(
                """
                EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
                SELECT id
                FROM transactions
                WHERE owner_id = :owner
                  AND status = 'posted'
                  AND occurred_at >= timestamptz '2024-01-01 00:00:00+00'
                  AND occurred_at < timestamptz '2024-02-01 00:00:00+00'
                ORDER BY occurred_at, id
                """
            ),
            {"owner": owner_id},
        ).scalar_one()
        plan = cast(dict[str, object], cast(list[dict[str, Any]], raw_plan)[0]["Plan"])

    nodes = list(_plan_nodes(plan))
    assert any(
        node.get("Index Name") == "ix_transactions_owner_id_occurred_at_id_posted" for node in nodes
    )
    assert not any(
        node.get("Node Type") == "Seq Scan" and node.get("Relation Name") == "transactions"
        for node in nodes
    )
    assert cast(int, plan["Actual Rows"]) <= 200
    assert sum(cast(int, node.get("Temp Read Blocks", 0)) for node in nodes) == 0
    assert sum(cast(int, node.get("Temp Written Blocks", 0)) for node in nodes) == 0

    factory = PostgresUnitOfWorkFactory(postgres_engine)
    service = AnalyticsService(factory, clock=lambda: Instant(NOW))
    select_count = 0

    def count_selects(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal select_count
        if statement.lstrip().upper().startswith("SELECT"):
            select_count += 1

    event.listen(postgres_engine, "before_cursor_execute", count_selects)
    try:
        service.report(
            owner_id,
            AnalyticsPeriod(
                date(2026, 10, 1),
                date(2026, 11, 1),
                "UTC",
                PeriodGranularity.MONTH,
            ),
        )
    finally:
        event.remove(postgres_engine, "before_cursor_execute", count_selects)
    assert select_count <= 5


def _plan_nodes(plan: dict[str, object]) -> tuple[dict[str, object], ...]:
    result = [plan]
    for child in cast(list[dict[str, object]], plan.get("Plans", [])):
        result.extend(_plan_nodes(child))
    return tuple(result)
