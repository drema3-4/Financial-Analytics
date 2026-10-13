from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol


class ReadinessDatabase(Protocol):
    def ping(self) -> bool: ...


class JobProcessor(Protocol):
    def tick(self, worker_id: str) -> object: ...


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
        self._path.write_text(str(self._clock()), encoding="ascii")

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
            return False
        if self._processor is not None:
            self._processor.tick(self._worker_id)
        self._heartbeat.mark()
        return True
