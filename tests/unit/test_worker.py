from __future__ import annotations

from pathlib import Path
from threading import Event
from unittest.mock import Mock

from financial_analytics_worker import Heartbeat, Worker, run_worker_loop


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


def test_worker_finishes_job_but_reports_unready_when_heartbeat_disk_write_fails(
    tmp_path: Path,
) -> None:
    processor = Mock()
    heartbeat = Heartbeat(tmp_path / "missing" / "heartbeat", clock=lambda: 100.0)
    worker = Worker(StubDatabase(ready=True), heartbeat, processor)

    assert worker.tick() is False
    processor.tick.assert_called_once_with("worker")


def test_graceful_stop_finishes_in_flight_tick_and_does_not_claim_another(tmp_path: Path) -> None:
    stop = Event()

    class StoppingProcessor:
        calls = 0

        def tick(self, _worker_id: str) -> None:
            self.calls += 1
            stop.set()

    processor = StoppingProcessor()
    worker = Worker(
        StubDatabase(ready=True),
        Heartbeat(tmp_path / "heartbeat", clock=lambda: 100.0),
        processor,
    )

    assert run_worker_loop(worker, stop, interval_seconds=0) == 0
    assert processor.calls == 1
    assert (tmp_path / "heartbeat").exists()
