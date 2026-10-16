from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import socket
import threading
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from uuid import uuid4

from financial_analytics_app import LedgerService, RecurringJobProcessor
from financial_analytics_domain import Instant
from financial_analytics_infra.database import Database
from financial_analytics_infra.logging import redact_sensitive_text
from financial_analytics_infra.repositories import PostgresUnitOfWorkFactory
from financial_analytics_infra.scheduling import PostgresSchedulingRepository
from financial_analytics_infra.settings import Settings
from financial_analytics_worker.worker import Heartbeat, Worker, run_worker_loop

HEARTBEAT_PATH = Path("/tmp/financial-analytics-worker-heartbeat")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Financial Analytics background worker")
    parser.add_argument("--healthcheck", action="store_true")
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


class WorkerJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_sensitive_text(record.getMessage()),
        }
        for name in ("event", "materialized", "claimed", "succeeded", "failed"):
            value = getattr(record, name, None)
            if value is not None:
                payload[name] = value
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(WorkerJsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def run() -> int:
    args = parse_args()
    settings = Settings()
    configure_logging(getattr(settings, "log_level", "INFO"))
    database = Database(settings.database_url)
    heartbeat = Heartbeat(HEARTBEAT_PATH)

    try:
        if args.healthcheck:
            return 0 if heartbeat.is_fresh() and database.ping() else 1

        scheduling = PostgresSchedulingRepository(database.engine)
        fixed_clock = settings.test_clock_at

        def clock() -> Instant:
            return Instant.now() if fixed_clock is None else Instant(fixed_clock)

        processor = RecurringJobProcessor(
            scheduling,
            LedgerService(PostgresUnitOfWorkFactory(database.engine), clock=clock),
            clock=clock,
        )
        worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
        worker = Worker(database, heartbeat, processor, worker_id=worker_id)
        stop_requested = threading.Event()

        def request_stop(_signal: int, _frame: FrameType | None) -> None:
            stop_requested.set()

        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)
        exit_code = run_worker_loop(worker, stop_requested, once=args.once)
        logger.info("Worker stopped after the active tick", extra={"event": "worker_stopped"})
        return exit_code
    finally:
        database.close()


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
