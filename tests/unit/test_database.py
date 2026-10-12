from __future__ import annotations

from financial_analytics_infra.database import Database


def test_database_ping_returns_false_instead_of_leaking_connection_errors() -> None:
    database = Database("postgresql+psycopg://user:password@127.0.0.1:1/unavailable")

    try:
        assert database.ping() is False
    finally:
        database.close()
