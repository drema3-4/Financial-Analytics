from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)


class ReadinessDatabase(Protocol):
    def ping(self) -> bool: ...


class JobProcessor(Protocol):
    def tick(self, worker_id: str) -> object: ...


class StopSignal(Protocol):
    def is_set(self) -> bool: ...

    def wait(self, timeout: float) -> object: ...


class Heartbeat:
    def __init__(
        self,
        path: Path,
        *,
        maximum_age_seconds: float = 30.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._path = path
        self._maximum_age_seconds = maximum_age_seconds
        self._clock = clock

    def mark(self) -> None:
        temporary = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temporary.write_text(str(self._clock()), encoding="ascii")
        temporary.replace(self._path)

    def is_fresh(self) -> bool:
        try:
            last_mark = float(self._path.read_text(encoding="ascii"))
        except (OSError, ValueError):
            return False
        age = self._clock() - last_mark
        return 0 <= age <= self._maximum_age_seconds


class Worker:
    """Readiness-aware wrapper around the durable recurring job processor."""

    def __init__(
        self,
        database: ReadinessDatabase,
        heartbeat: Heartbeat,
        processor: JobProcessor | None = None,
        *,
        worker_id: str = "worker",
    ) -> None:
        self._database = database
        self._heartbeat = heartbeat
        self._processor = processor
        self._worker_id = worker_id

    def tick(self) -> bool:
        if not self._database.ping():
            logger.warning("Worker database is not ready", extra={"event": "worker_not_ready"})
            return False
        if self._processor is not None:
            result = self._processor.tick(self._worker_id)
            logger.info(
                "Worker tick completed",
                extra={
                    "event": "worker_tick",
                    "materialized": getattr(result, "materialized", 0),
                    "claimed": getattr(result, "claimed", 0),
                    "succeeded": getattr(result, "succeeded", 0),
                    "failed": getattr(result, "failed", 0),
                },
            )
        try:
            self._heartbeat.mark()
        except OSError:
            logger.error("Worker heartbeat write failed", extra={"event": "heartbeat_failed"})
            return False
        return True


def run_worker_loop(
    worker: Worker,
    stop_requested: StopSignal,
    *,
    once: bool = False,
    interval_seconds: float = 5,
) -> int:
    """Finish the current synchronous tick and never claim another after stop."""

    while not stop_requested.is_set():
        worker.tick()
        if once:
            return 0
        stop_requested.wait(interval_seconds)
    return 0
