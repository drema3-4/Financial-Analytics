from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, inspect, text

from financial_analytics_api.main import create_app
from financial_analytics_infra.settings import AppEnvironment, Settings

FIXED_NOW = datetime(2026, 10, 16, 8, tzinfo=UTC)


def _headers(client: TestClient, key: str) -> dict[str, str]:
    csrf = client.cookies.get("fa_csrf")
    if csrf is None:
        raise RuntimeError("bootstrap did not issue a CSRF token")
    return {"X-CSRF-Token": csrf, "Idempotency-Key": key}


def seed(database_url: str) -> None:
    settings = Settings(
        app_env=AppEnvironment.TEST,
        database_url_secret=SecretStr(database_url),
        test_clock_at=FIXED_NOW,
        _env_file=None,
    )
    with TestClient(create_app(settings), base_url="https://testserver") as client:
        created = client.post(
            "/api/v1/auth/bootstrap",
            json={
                "email": "restore-drill@example.test",
                "password": "restore drill password 2026",
                "base_currency": "RUB",
                "locale": "ru-RU",
                "timezone": "Europe/Saratov",
            },
        )
        _expect(created.status_code, 201, created.text)
        _install_access_cookie(client, created.headers.get_list("set-cookie"))
        account_response = client.post(
            "/api/v1/accounts",
            json={
                "name": "Restore drill account",
                "kind": "bank",
                "currency": "RUB",
                "opening_balance": {"amount": "1000.00", "currency": "RUB"},
                "opening_balance_occurred_at": FIXED_NOW.isoformat(),
            },
            headers=_headers(client, "restore-account"),
        )
        _expect(account_response.status_code, 201, account_response.text)
        category_response = client.post(
            "/api/v1/categories",
            json={"name": "Restore drill expense", "kind": "expense"},
            headers=_headers(client, "restore-category"),
        )
        _expect(category_response.status_code, 201, category_response.text)
        expense = client.post(
            "/api/v1/transactions/expense",
            json={
                "account_id": account_response.json()["id"],
                "category_id": category_response.json()["id"],
                "money": {"amount": "125.25", "currency": "RUB"},
                "occurred_at": FIXED_NOW.isoformat(),
                "description": "Restore drill financial fact",
                "source": "manual",
            },
            headers=_headers(client, "restore-expense"),
        )
        _expect(expense.status_code, 201, expense.text)


def database_fingerprint(database_url: str) -> tuple[str, dict[str, tuple[int, str]]]:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            revision = str(connection.scalar(text("SELECT version_num FROM alembic_version")))
            tables: dict[str, tuple[int, str]] = {}
            for table_name in sorted(inspect(connection).get_table_names(schema="public")):
                quoted_table = engine.dialect.identifier_preparer.quote(table_name)
                rows = connection.execute(text(f"SELECT * FROM {quoted_table}")).mappings()
                canonical = sorted(
                    json.dumps(dict(row), sort_keys=True, default=str, separators=(",", ":"))
                    for row in rows
                )
                digest = hashlib.sha256("\n".join(canonical).encode()).hexdigest()
                tables[table_name] = (len(canonical), digest)
            unbalanced = connection.scalar(
                text(
                    """
                    SELECT count(*) FROM (
                      SELECT transaction_id, currency
                      FROM postings
                      GROUP BY transaction_id, currency
                      HAVING sum(amount) <> 0
                    ) AS invalid
                    """
                )
            )
            if unbalanced != 0:
                raise RuntimeError("ledger is not balanced")
            return revision, tables
    finally:
        engine.dispose()


def verify(source_url: str, restore_url: str) -> None:
    if source_url == restore_url:
        raise RuntimeError("source and restore URLs must differ")
    source = database_fingerprint(source_url)
    restored = database_fingerprint(restore_url)
    if source != restored:
        raise RuntimeError("restored schema or data fingerprint differs from source")
    print("restore drill verified: revision, all table rows, digests, and ledger balance match")


def _expect(actual: int, expected: int, detail: str) -> None:
    if actual != expected:
        raise RuntimeError(f"seed request failed with status {actual}: {detail}")


def _install_access_cookie(client: TestClient, set_cookie_headers: list[str]) -> None:
    for header in set_cookie_headers:
        pair = header.split(";", 1)[0]
        name, separator, value = pair.partition("=")
        if separator and name == "fa_access":
            # The server clock is deliberately fixed. Normalize only the browser-side expiry;
            # the signed token and database session still use and enforce the fixed clock.
            client.cookies.set(name, value, domain="testserver.local", path="/")
            return
    raise RuntimeError("bootstrap did not issue an access cookie")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("seed", "verify"))
    args = parser.parse_args()
    if args.operation == "seed":
        seed(_required_environment("DATABASE_URL"))
        return
    verify(
        _required_environment("SOURCE_DATABASE_URL"),
        _required_environment("RESTORE_DATABASE_URL"),
    )


def _required_environment(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


if __name__ == "__main__":
    main()
