from __future__ import annotations

import csv
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from financial_analytics_api.main import create_app
from financial_analytics_app.identity import (
    AuthenticatedSession,
    AuthService,
    CsrfValidationError,
)
from financial_analytics_app.ledger import LedgerService
from financial_analytics_domain import (
    Currency,
    EmailAddress,
    Instant,
    UserProfile,
    UserStatus,
)
from financial_analytics_infra.models import (
    AccountModel,
    IdempotencyRecordModel,
    TransactionModel,
    TransactionTagModel,
    UserModel,
)
from financial_analytics_infra.repositories import PostgresUnitOfWorkFactory
from financial_analytics_infra.settings import AppEnvironment, Settings

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)


class StubApiAuth:
    def __init__(self, profiles: dict[str, UserProfile]) -> None:
        self._profiles = profiles

    def authenticate_access(self, raw_token: str) -> AuthenticatedSession:
        profile = self._profiles[raw_token]
        return AuthenticatedSession(profile, uuid4(), "unused-in-stub")

    def verify_csrf(
        self,
        authenticated: AuthenticatedSession,
        *,
        cookie_token: str | None,
        header_token: str | None,
    ) -> None:
        expected = f"csrf-{authenticated.profile.id}"
        if cookie_token != expected or header_token != expected:
            raise CsrfValidationError("invalid csrf")


def _profile(owner_id: UUID, email: str) -> UserProfile:
    return UserProfile(
        id=owner_id,
        email=EmailAddress(email),
        base_currency=Currency("RUB"),
        locale="ru-RU",
        timezone="Europe/Saratov",
        status=UserStatus.ACTIVE,
        is_master=False,
        created_at=Instant(NOW),
    )


def _make_app(engine: Engine, owners: dict[str, UUID]) -> object:
    profiles = {token: _profile(owner, f"{token}@example.test") for token, owner in owners.items()}
    auth = StubApiAuth(profiles)

    async def ready() -> bool:
        return True

    return create_app(
        Settings(app_env=AppEnvironment.TEST, _env_file=None),
        ready,
        cast(AuthService, auth),
        LedgerService(PostgresUnitOfWorkFactory(engine)),
    )


def _client(app: object, token: str, owner_id: UUID) -> TestClient:
    client = TestClient(app, base_url="https://testserver")  # type: ignore[arg-type]
    client.cookies.set("fa_access", token)
    client.cookies.set("fa_csrf", f"csrf-{owner_id}")
    return client


def _mutation_headers(owner_id: UUID, key: str) -> dict[str, str]:
    return {"X-CSRF-Token": f"csrf-{owner_id}", "Idempotency-Key": key}


def _insert_owners(engine: Engine, *owner_ids: UUID) -> None:
    with Session(engine) as session:
        session.add_all(UserModel(id=owner_id) for owner_id in owner_ids)
        session.commit()


def _create_account(
    client: TestClient,
    owner_id: UUID,
    key: str,
    name: str,
    opening: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"name": name, "kind": "bank", "currency": "RUB"}
    if opening is not None:
        payload.update(
            {
                "opening_balance": {"amount": opening, "currency": "RUB"},
                "opening_balance_occurred_at": NOW.isoformat(),
            }
        )
    response = client.post(
        "/api/v1/accounts", json=payload, headers=_mutation_headers(owner_id, key)
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, object], response.json())


def test_concurrent_idempotent_account_creation_is_single_posting(
    postgres_engine: Engine,
) -> None:
    owner_id = uuid4()
    _insert_owners(postgres_engine, owner_id)
    app = _make_app(postgres_engine, {"owner": owner_id})
    payload = {
        "name": "Concurrent",
        "kind": "bank",
        "currency": "RUB",
        "opening_balance": {"amount": "100.00", "currency": "RUB"},
        "opening_balance_occurred_at": NOW.isoformat(),
    }

    def create() -> tuple[int, str]:
        with _client(app, "owner", owner_id) as client:
            response = client.post(
                "/api/v1/accounts",
                json=payload,
                headers=_mutation_headers(owner_id, "same-concurrent-command"),
            )
            return response.status_code, response.json().get("id", response.text)

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: create(), range(6)))

    assert {status for status, _ in results} == {201}
    assert len({resource_id for _, resource_id in results}) == 1
    with Session(postgres_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AccountModel)
                .where(AccountModel.owner_id == owner_id)
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(TransactionModel)
                .where(TransactionModel.owner_id == owner_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(IdempotencyRecordModel)
                .where(IdempotencyRecordModel.owner_id == owner_id)
            )
            == 1
        )


def test_income_expense_transfer_reversal_duplicate_key_and_owner_isolation(
    postgres_engine: Engine,
) -> None:
    owner_id, other_owner_id = uuid4(), uuid4()
    _insert_owners(postgres_engine, owner_id, other_owner_id)
    app = _make_app(postgres_engine, {"first": owner_id, "second": other_owner_id})
    with (
        _client(app, "first", owner_id) as client,
        _client(app, "second", other_owner_id) as other,
    ):
        bank = _create_account(client, owner_id, "bank", "Bank")
        cash = _create_account(client, owner_id, "cash", "Cash")
        duplicate = client.post(
            "/api/v1/accounts",
            json={"name": "Bank", "kind": "bank", "currency": "RUB"},
            headers=_mutation_headers(owner_id, "bank"),
        )
        assert duplicate.status_code == 201
        assert duplicate.json() == bank
        conflict = client.post(
            "/api/v1/accounts",
            json={"name": "Changed", "kind": "bank", "currency": "RUB"},
            headers=_mutation_headers(owner_id, "bank"),
        )
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "idempotency_conflict"

        group = client.post(
            "/api/v1/category-groups",
            json={"name": "Everyday"},
            headers=_mutation_headers(owner_id, "group"),
        ).json()
        income_category = client.post(
            "/api/v1/categories",
            json={"name": "Salary", "kind": "income", "group_id": group["id"]},
            headers=_mutation_headers(owner_id, "income-category"),
        ).json()
        expense_category = client.post(
            "/api/v1/categories",
            json={"name": "Food", "kind": "expense", "group_id": group["id"]},
            headers=_mutation_headers(owner_id, "expense-category"),
        ).json()
        grouped = client.get("/api/v1/category-groups")
        assert grouped.status_code == 200
        assert {item["name"] for item in grouped.json()[0]["categories"]} == {
            "Salary",
            "Food",
        }
        tag = client.post(
            "/api/v1/tags",
            json={"name": "work"},
            headers=_mutation_headers(owner_id, "work-tag"),
        ).json()

        def operation_payload(
            category_id: str, amount: object, description: str
        ) -> dict[str, object]:
            return {
                "account_id": bank["id"],
                "category_id": category_id,
                "money": {"amount": amount, "currency": "RUB"},
                "occurred_at": NOW.isoformat(),
                "description": description,
            }

        float_rejected = client.post(
            "/api/v1/transactions/income",
            json=operation_payload(income_category["id"], 1000.0, "Salary"),
            headers=_mutation_headers(owner_id, "float"),
        )
        assert float_rejected.status_code == 422
        assert float_rejected.json()["code"] == "validation_error"

        income_payload = operation_payload(income_category["id"], "1000.00", "Salary")
        income_payload["tag_ids"] = [tag["id"]]
        income = client.post(
            "/api/v1/transactions/income",
            json=income_payload,
            headers=_mutation_headers(owner_id, "income"),
        )
        assert income.status_code == 201, income.text
        expense = client.post(
            "/api/v1/transactions/expense",
            json=operation_payload(expense_category["id"], "125.25", "Food"),
            headers=_mutation_headers(owner_id, "expense"),
        )
        assert expense.status_code == 201, expense.text
        transfer = client.post(
            "/api/v1/transfers",
            json={
                "source_account_id": bank["id"],
                "destination_account_id": cash["id"],
                "money": {"amount": "200.00", "currency": "RUB"},
                "occurred_at": NOW.isoformat(),
                "description": "Cash",
            },
            headers=_mutation_headers(owner_id, "transfer"),
        )
        assert transfer.status_code == 201, transfer.text
        reversal = client.post(
            f"/api/v1/transactions/{expense.json()['id']}/reversal",
            json={"occurred_at": (NOW + timedelta(minutes=1)).isoformat(), "reason": "Wrong"},
            headers=_mutation_headers(owner_id, "reverse-expense"),
        )
        assert reversal.status_code == 201, reversal.text

        account_rows = client.get("/api/v1/accounts").json()
        balances = {item["name"]: item["balance"]["amount"] for item in account_rows}
        assert balances == {"Bank": "800.00", "Cash": "200.00"}
        assert [item["money"]["amount"] for item in income.json()["postings"]] == [
            "1000.00",
            "-1000.00",
        ]

        transaction_id = income.json()["id"]
        assert other.get(f"/api/v1/transactions/{transaction_id}").status_code == 404
        assert other.get(f"/api/v1/accounts/{bank['id']}").status_code == 404
        assert client.delete(f"/api/v1/transactions/{transaction_id}").status_code == 405
        assert client.get(f"/api/v1/transactions/{transaction_id}").status_code == 200

        with Session(postgres_engine) as session, pytest.raises(DBAPIError):
            session.execute(
                delete(TransactionTagModel).where(
                    TransactionTagModel.owner_id == owner_id,
                    TransactionTagModel.transaction_id == UUID(transaction_id),
                )
            )
            session.commit()


def test_cursor_stability_and_utf8_csv_escaping(postgres_engine: Engine) -> None:
    owner_id = uuid4()
    _insert_owners(postgres_engine, owner_id)
    app = _make_app(postgres_engine, {"owner": owner_id})
    with _client(app, "owner", owner_id) as client:
        account = _create_account(client, owner_id, "pagination-account", "Journal")
        descriptions = ['  =HYPERLINK("https://evil.test",кофе)\nвторая строка', "middle", "oldest"]
        transaction_ids: list[str] = []
        for index, description in enumerate(descriptions):
            response = client.post(
                "/api/v1/adjustments",
                json={
                    "account_id": account["id"],
                    "money": {"amount": "1.00", "currency": "RUB"},
                    "occurred_at": (NOW - timedelta(minutes=index)).isoformat(),
                    "description": description,
                },
                headers=_mutation_headers(owner_id, f"adjustment-{index}"),
            )
            assert response.status_code == 201, response.text
            transaction_ids.append(response.json()["id"])

        first_page = client.get("/api/v1/transactions", params={"kind": "adjustment", "limit": 2})
        assert first_page.status_code == 200
        assert [item["id"] for item in first_page.json()["items"]] == transaction_ids[:2]
        cursor = first_page.json()["next_cursor"]
        assert cursor

        inserted = client.post(
            "/api/v1/adjustments",
            json={
                "account_id": account["id"],
                "money": {"amount": "1.00", "currency": "RUB"},
                "occurred_at": (NOW - timedelta(minutes=5)).isoformat(),
                "description": "backdated after page one",
            },
            headers=_mutation_headers(owner_id, "adjustment-new"),
        )
        assert inserted.status_code == 201
        second_page = client.get(
            "/api/v1/transactions",
            params={"kind": "adjustment", "limit": 2, "cursor": cursor},
        )
        assert [item["id"] for item in second_page.json()["items"]] == [transaction_ids[2]]

        injection_search = client.get(
            "/api/v1/transactions",
            params={"search": "' OR 1=1 --", "limit": 100},
        )
        assert injection_search.status_code == 200
        assert injection_search.json()["items"] == []

        exported = client.get("/api/v1/transactions/export.csv", params={"kind": "adjustment"})
        assert exported.status_code == 200
        assert exported.content.startswith(b"\xef\xbb\xbf")
        assert "text/csv" in exported.headers["content-type"]
        assert exported.headers["content-disposition"] == 'attachment; filename="transactions.csv"'
        assert exported.headers["x-content-type-options"] == "nosniff"
        assert exported.headers["cache-control"] == "no-store"
        rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
        original = next(row for row in rows if row["id"] == transaction_ids[0])
        assert original["description"] == "'" + descriptions[0]
