from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from financial_analytics_api.main import create_app
from financial_analytics_app.deposits import DepositService
from financial_analytics_app.identity import AuthService
from financial_analytics_app.ledger import LedgerService
from financial_analytics_domain import Instant
from financial_analytics_infra.models import AuditEventModel, DepositTermsModel, TransactionModel
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
NOW = datetime(2024, 1, 1, 9, tzinfo=UTC)


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
        ledger_service=LedgerService(factory, clock=lambda: Instant(NOW)),
        deposit_service=DepositService(factory, clock=lambda: Instant(NOW)),
    )


def _account(
    client: TestClient, owner_id: UUID, *, name: str, kind: str, key: str
) -> dict[str, object]:
    response = client.post(
        "/api/v1/accounts",
        json={"name": name, "kind": kind, "currency": "USD"},
        headers=_mutation_headers(owner_id, key),
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, object], response.json())


def test_deposit_cashflows_interest_reconciliation_audit_and_owner_isolation(
    postgres_engine: Engine,
) -> None:
    owner_id, other_owner_id = uuid4(), uuid4()
    _insert_owners(postgres_engine, owner_id, other_owner_id)
    app = _make_app(postgres_engine, {"owner": owner_id, "other": other_owner_id})
    with (
        _client(app, "owner", owner_id) as client,
        _client(app, "other", other_owner_id) as other,
    ):
        bank = _account(client, owner_id, name="Bank", kind="bank", key="bank")
        payload = {
            "name": "Deposit",
            "opening_balance": {"amount": "900.00", "currency": "USD"},
            "currency": "USD",
            "opened_on": "2024-01-01",
            "matures_on": "2024-01-04",
            "rate_periods": [
                {
                    "starts_on": "2024-01-01",
                    "ends_on": "2024-01-04",
                    "nominal_rate": {"value": "0.365"},
                }
            ],
            "capitalization_frequency": "monthly_calendar_end",
            "day_count_convention": "actual_365_fixed",
            "rounding_policy": "half_up",
            "interest_rounding_frequency": "capitalization",
            "timezone": "UTC",
            "cashflow_cutoff_time": "12:00:00",
            "cashflow_cutoff_inclusive": True,
            "early_close_rule": {"policy": "forbid", "nominal_rate": None},
            "tax_rate": {"value": "0"},
        }
        created = client.post(
            "/api/v1/deposits",
            json=payload,
            headers=_mutation_headers(owner_id, "deposit-create"),
        )
        assert created.status_code == 201, created.text
        deposit_id = created.json()["id"]
        replay = client.post(
            "/api/v1/deposits",
            json=payload,
            headers=_mutation_headers(owner_id, "deposit-create"),
        )
        assert replay.json()["id"] == deposit_id

        funding = client.post(
            f"/api/v1/deposits/{deposit_id}/cashflows",
            json={
                "counterparty_account_id": bank["id"],
                "money": {"amount": "100.00", "currency": "USD"},
                "occurred_at": NOW.isoformat(),
                "description": "Opening funding",
            },
            headers=_mutation_headers(owner_id, "funding"),
        )
        assert funding.status_code == 201, funding.text
        assert funding.json()["kind"] == "transfer"
        assert funding.json()["deposit_id"] == deposit_id

        first_actual = client.post(
            f"/api/v1/deposits/{deposit_id}/interest-postings",
            json={
                "money": {"amount": "2.90", "currency": "USD"},
                "occurred_at": "2024-01-04T09:00:00+00:00",
                "description": "Bank interest before correction",
            },
            headers=_mutation_headers(owner_id, "interest-original"),
        )
        assert first_actual.status_code == 201, first_actual.text
        reversal = client.post(
            f"/api/v1/transactions/{first_actual.json()['id']}/reversal",
            json={
                "occurred_at": "2024-01-04T09:01:00+00:00",
                "reason": "Bank corrected its posting",
            },
            headers=_mutation_headers(owner_id, "interest-reversal"),
        )
        assert reversal.status_code == 201, reversal.text
        assert reversal.json()["deposit_id"] == deposit_id
        corrected = client.post(
            f"/api/v1/deposits/{deposit_id}/interest-postings",
            json={
                "money": {"amount": "3.00", "currency": "USD"},
                "occurred_at": "2024-01-04T09:02:00+00:00",
                "description": "Corrected bank interest",
            },
            headers=_mutation_headers(owner_id, "interest-corrected"),
        )
        assert corrected.status_code == 201, corrected.text

        valuation = client.get(
            f"/api/v1/deposits/{deposit_id}/valuation", params={"as_of": "2024-01-04"}
        )
        assert valuation.status_code == 200, valuation.text
        body = valuation.json()
        assert body["algorithm_version"] == "deposit-interest-v1"
        assert body["projected_maturity_value"]["amount"] == "1003.00"
        assert body["schedule"] == [
            {
                "accrual_starts_on": "2024-01-01",
                "accrual_ends_on": "2024-01-04",
                "posting_date": "2024-01-04",
                "opening_balance": {"amount": "0.00", "currency": "USD"},
                "cashflow": {"amount": "1000.00", "currency": "USD"},
                "gross_interest": {"amount": "3.00", "currency": "USD"},
                "tax": {"amount": "0.00", "currency": "USD"},
                "net_interest": {"amount": "3.00", "currency": "USD"},
                "closing_balance": {"amount": "1003.00", "currency": "USD"},
            }
        ]
        assert body["reconciliation"] == [
            {
                "posting_date": "2024-01-04",
                "planned_interest": {"amount": "3.00", "currency": "USD"},
                "actual_interest": {"amount": "3.00", "currency": "USD"},
                "variance": {"amount": "0.00", "currency": "USD"},
            }
        ]
        assert client.get(f"/api/v1/deposits/{deposit_id}").json() == created.json()
        assert other.get(f"/api/v1/deposits/{deposit_id}").status_code == 404
        assert (
            other.get(
                f"/api/v1/deposits/{deposit_id}/valuation",
                params={"as_of": "2024-01-04"},
            ).status_code
            == 404
        )

    with Session(postgres_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(DepositTermsModel)
                .where(DepositTermsModel.owner_id == owner_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(TransactionModel)
                .where(
                    TransactionModel.owner_id == owner_id,
                    TransactionModel.deposit_id == UUID(deposit_id),
                )
            )
            == 4
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEventModel)
                .where(
                    AuditEventModel.owner_id == owner_id,
                    AuditEventModel.event_type == "deposit.interest_recorded",
                )
            )
            == 2
        )
    with Session(postgres_engine) as session, pytest.raises(DBAPIError):
        session.execute(delete(DepositTermsModel).where(DepositTermsModel.id == UUID(deposit_id)))
        session.commit()
