from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy import Engine, select

from financial_analytics_app.deposits import DepositService
from financial_analytics_app.mail import EmailJobTickResult
from financial_analytics_domain import Instant
from financial_analytics_infra.models import DepositTermsModel
from financial_analytics_infra.repositories import PostgresUnitOfWorkFactory

logger = logging.getLogger(__name__)


class DepositAccrualProcessor:
    """Enumerate active owners, then reconcile every tenant in its own transaction."""

    def __init__(self, engine: Engine, *, clock: Callable[[], Instant] = Instant.now) -> None:
        self._engine = engine
        self._service = DepositService(PostgresUnitOfWorkFactory(engine), clock=clock)

    def tick(self, worker_id: str) -> EmailJobTickResult:
        with self._engine.connect() as connection:
            owners = connection.scalars(
                select(DepositTermsModel.owner_id)
                .where(DepositTermsModel.archived.is_(False))
                .distinct()
            ).all()
        succeeded = failed = 0
        for owner_id in owners:
            try:
                self._service.accrue_due(owner_id)
            except Exception:
                # Financial details and exception inputs are deliberately absent from logs.
                logger.error(
                    "Deposit reconciliation failed", extra={"event": "deposit_accrual_failed"}
                )
                failed += 1
            else:
                succeeded += 1
        return EmailJobTickResult(0, len(owners), succeeded, failed)
