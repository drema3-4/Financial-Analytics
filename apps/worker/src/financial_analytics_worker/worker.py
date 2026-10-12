from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol


class ReadinessDatabase(Protocol):
    def ping(self) -> bool: ...


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
    """Bootstrap worker loop; durable job handling is introduced in milestone 05."""

    def __init__(self, database: ReadinessDatabase, heartbeat: Heartbeat) -> None:
        self._database = database
        self._heartbeat = heartbeat

    def tick(self) -> bool:
        if not self._database.ping():
            return False
        self._heartbeat.mark()
        return True
