from __future__ import annotations

import json
import logging
from argparse import Namespace
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

import financial_analytics_api.__main__ as api_entrypoint
import financial_analytics_api.main as api_main
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
        "timeout_graceful_shutdown": 30,
    }


def test_api_lifespan_disposes_database_resources_on_graceful_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = LifespanDatabase()
    identity_store = LifespanIdentityStore()
    monkeypatch.setattr(api_main, "Database", lambda _: database)
    monkeypatch.setattr(api_main, "PostgresIdentityStore", lambda _: identity_store)

    app = api_main.create_app()
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert database.closed is False
        assert identity_store.closed is False

    assert database.closed is True
    assert identity_store.closed is True


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


def test_worker_json_logging_redacts_sensitive_text() -> None:
    record = logging.LogRecord(
        "worker",
        logging.ERROR,
        __file__,
        1,
        "token=worker-secret owner@example.test 4111 1111 1111 1111",
        (),
        None,
    )

    payload = json.loads(worker_entrypoint.WorkerJsonFormatter().format(record))

    assert payload["message"].count("[REDACTED]") == 3
    assert "worker-secret" not in payload["message"]


class FakeDatabase:
    def __init__(self) -> None:
        self.closed = False

    def ping(self) -> bool:
        return True

    def close(self) -> None:
        self.closed = True


class LifespanDatabase(FakeDatabase):
    engine = object()

    def job_queue_snapshot(self) -> object:
        raise AssertionError("the shutdown test must not query the job queue")


class LifespanIdentityStore:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FreshHeartbeat:
    def is_fresh(self) -> bool:
        return True
