from __future__ import annotations

import argparse
import logging
import os
import socket
import time
from pathlib import Path
from uuid import uuid4

from financial_analytics_app import LedgerService, RecurringJobProcessor
from financial_analytics_infra.database import Database
from financial_analytics_infra.repositories import PostgresUnitOfWorkFactory
from financial_analytics_infra.scheduling import PostgresSchedulingRepository
from financial_analytics_infra.settings import Settings
from financial_analytics_worker.worker import Heartbeat, Worker

HEARTBEAT_PATH = Path("/tmp/financial-analytics-worker-heartbeat")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Financial Analytics background worker")
    parser.add_argument("--healthcheck", action="store_true")
    return parser.parse_args()


def run() -> int:
    args = parse_args()
    settings = Settings()
    database = Database(settings.database_url)
    heartbeat = Heartbeat(HEARTBEAT_PATH)

    try:
        if args.healthcheck:
            return 0 if heartbeat.is_fresh() and database.ping() else 1

        scheduling = PostgresSchedulingRepository(database.engine)
        processor = RecurringJobProcessor(
            scheduling,
            LedgerService(PostgresUnitOfWorkFactory(database.engine)),
        )
        worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
        worker = Worker(database, heartbeat, processor, worker_id=worker_id)
        while True:
            if not worker.tick():
                logger.warning("Worker is waiting for the database")
            time.sleep(5)
    except KeyboardInterrupt:
        return 0
    finally:
        database.close()


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
