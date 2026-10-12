from __future__ import annotations

from pathlib import Path

from financial_analytics_worker import Heartbeat, Worker


class StubDatabase:
    def __init__(self, ready: bool) -> None:
        self.ready = ready

    def ping(self) -> bool:
        return self.ready


def test_worker_marks_heartbeat_only_after_database_is_ready(tmp_path: Path) -> None:
    now = 100.0
    path = tmp_path / "heartbeat"
    heartbeat = Heartbeat(path, clock=lambda: now)
    database = StubDatabase(ready=False)
    worker = Worker(database, heartbeat)

    assert worker.tick() is False
    assert heartbeat.is_fresh() is False

    database.ready = True
    assert worker.tick() is True
    assert heartbeat.is_fresh() is True


def test_heartbeat_expires_and_rejects_future_timestamps(tmp_path: Path) -> None:
    now = 100.0
    path = tmp_path / "heartbeat"
    heartbeat = Heartbeat(path, maximum_age_seconds=10, clock=lambda: now)

    path.write_text("89", encoding="ascii")
    assert heartbeat.is_fresh() is False

    path.write_text("101", encoding="ascii")
    assert heartbeat.is_fresh() is False

    path.write_text("not-a-number", encoding="ascii")
    assert heartbeat.is_fresh() is False
