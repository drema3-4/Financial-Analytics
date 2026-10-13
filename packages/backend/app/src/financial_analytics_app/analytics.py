from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from financial_analytics_app.ports import UnitOfWorkFactory
from financial_analytics_domain import (
    AnalyticsPeriod,
    AnalyticsReport,
    Instant,
    build_analytics_report,
)


class AnalyticsService:
    """Owner-scoped application queries over immutable ledger facts."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        *,
        clock: Callable[[], Instant] = Instant.now,
    ) -> None:
        self._uow_factory = unit_of_work_factory
        self._clock = clock

    def report(self, owner_id: UUID, period: AnalyticsPeriod) -> AnalyticsReport:
        with self._uow_factory.open(owner_id) as uow:
            accounts = uow.ledger.list_accounts(include_archived=True)
            categories = uow.ledger.list_categories()
            groups = uow.ledger.list_category_groups()
            transactions = uow.ledger.list_analytics_transactions(period.end_at)
        return build_analytics_report(
            accounts=accounts,
            categories=categories,
            groups=groups,
            transactions=transactions,
            period=period,
            now=self._clock().value,
        )

    def now(self) -> datetime:
        return self._clock().value
