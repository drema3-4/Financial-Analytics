from __future__ import annotations

from argparse import Namespace
from types import SimpleNamespace
from typing import Any

import pytest

import financial_analytics_api.__main__ as api_entrypoint
import financial_analytics_app
import financial_analytics_domain
import financial_analytics_worker.__main__ as worker_entrypoint


def test_backend_dependency_boundaries_are_importable() -> None:
    assert financial_analytics_app.__doc__
    assert financial_analytics_domain.__doc__


def test_api_entrypoint_uses_the_expected_safe_server_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_run(target: str, **options: Any) -> None:
        captured["target"] = target
        captured.update(options)

    monkeypatch.setattr("financial_analytics_api.__main__.uvicorn.run", fake_run)

    api_entrypoint.main()

    assert captured == {
        "target": "financial_analytics_api.main:app",
        "host": "0.0.0.0",
        "port": 8000,
        "proxy_headers": False,
        "access_log": False,
        "log_config": None,
    }


def test_worker_healthcheck_closes_database(monkeypatch: pytest.MonkeyPatch) -> None:
    database = FakeDatabase()
    monkeypatch.setattr(worker_entrypoint, "parse_args", lambda: Namespace(healthcheck=True))
    monkeypatch.setattr(
        worker_entrypoint,
        "Settings",
        lambda: SimpleNamespace(database_url="postgresql+psycopg://unused"),
    )
    monkeypatch.setattr(worker_entrypoint, "Database", lambda _: database)
    monkeypatch.setattr(worker_entrypoint, "Heartbeat", lambda _: FreshHeartbeat())

    assert worker_entrypoint.run() == 0
    assert database.closed is True


class FakeDatabase:
    def __init__(self) -> None:
        self.closed = False

    def ping(self) -> bool:
        return True

    def close(self) -> None:
        self.closed = True


class FreshHeartbeat:
    def is_fresh(self) -> bool:
        return True
