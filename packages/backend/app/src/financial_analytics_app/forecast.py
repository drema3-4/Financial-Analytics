from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from financial_analytics_app.deposit_ledger import principal_cashflows
from financial_analytics_app.ledger import ResourceConflictError, ResourceNotFoundError
from financial_analytics_app.ports import (
    AuditEvent,
    IdempotencyRecord,
    UnitOfWork,
    UnitOfWorkFactory,
)
from financial_analytics_app.services import IdempotencyConflictError
from financial_analytics_domain import (
    Account,
    Currency,
    FinancialGoal,
    ForecastAccount,
    ForecastAssumptions,
    ForecastCashflow,
    ForecastFlowKind,
    ForecastInputSnapshot,
    ForecastResult,
    ForecastScenario,
    GoalPlanResult,
    HistoricalExpenseSample,
    Instant,
    Money,
    RecurringRule,
    RecurringRuleStatus,
    Transaction,
    TransactionKind,
    forecast_finances,
    next_occurrence,
    plan_goals,
    project_deposit,
)
from financial_analytics_domain.errors import OwnershipError

HISTORY_MONTHS = 6


@dataclass(frozen=True, slots=True)
class ForecastComparisonItem:
    scenario_id: UUID | None
    scenario_name: str
    forecast: ForecastResult
    goal_plan: GoalPlanResult


@dataclass(frozen=True, slots=True)
class ForecastComparison:
    snapshot_id: str
    items: tuple[ForecastComparisonItem, ...]


class ForecastService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        uuid_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], Instant] = Instant.now,
    ) -> None:
        self._uow_factory = uow_factory
        self._uuid_factory = uuid_factory
        self._clock = clock

    def create_scenario(
        self,
        *,
        scenario: ForecastScenario,
        actor_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: UUID | None,
    ) -> ForecastScenario:
        if scenario.owner_id != actor_id:
            raise OwnershipError("actor must own the forecast scenario")
        with self._uow_factory.open(scenario.owner_id) as uow:
            replay_id = self._lock_and_replay(
                uow, "create_forecast_scenario", idempotency_key, request_hash
            )
            if replay_id is not None:
                replay = uow.forecasts.get_scenario(replay_id)
                if replay is None:
                    raise RuntimeError("idempotency record points to a missing scenario")
                return replay
            self._validate_scenario_accounts(uow, scenario)
            uow.forecasts.add_scenario(scenario)
            self._audit(
                uow,
                actor_id,
                "forecast.scenario_created",
                "forecast_scenario",
                scenario.id,
                request_id,
                {"assumptions_version": scenario.assumptions.version},
            )
            self._remember(
                uow,
                scenario.owner_id,
                "create_forecast_scenario",
                idempotency_key,
                request_hash,
                "forecast_scenario",
                scenario.id,
            )
            uow.commit()
            return scenario

    def update_scenario(
        self,
        *,
        scenario: ForecastScenario,
        actor_id: UUID,
        expected_version: int,
        request_id: UUID | None,
    ) -> ForecastScenario:
        if scenario.owner_id != actor_id:
            raise OwnershipError("actor must own the forecast scenario")
        with self._uow_factory.open(scenario.owner_id) as uow:
            if uow.forecasts.get_scenario(scenario.id) is None:
                raise ResourceNotFoundError("forecast scenario was not found")
            self._validate_scenario_accounts(uow, scenario)
            saved = uow.forecasts.save_scenario(scenario, expected_version=expected_version)
            self._audit(
                uow,
                actor_id,
                "forecast.scenario_updated",
                "forecast_scenario",
                scenario.id,
                request_id,
                {"previous_version": expected_version, "version": saved.version},
            )
            uow.commit()
            return saved

    def list_scenarios(self, owner_id: UUID) -> tuple[ForecastScenario, ...]:
        with self._uow_factory.open(owner_id) as uow:
            return uow.forecasts.list_scenarios()

    def get_scenario(self, owner_id: UUID, scenario_id: UUID) -> ForecastScenario:
        with self._uow_factory.open(owner_id) as uow:
            scenario = uow.forecasts.get_scenario(scenario_id)
            if scenario is None:
                raise ResourceNotFoundError("forecast scenario was not found")
            return scenario

    def create_goal(
        self,
        *,
        goal: FinancialGoal,
        actor_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: UUID | None,
    ) -> FinancialGoal:
        if goal.owner_id != actor_id:
            raise OwnershipError("actor must own the financial goal")
        with self._uow_factory.open(goal.owner_id) as uow:
            replay_id = self._lock_and_replay(
                uow, "create_financial_goal", idempotency_key, request_hash
            )
            if replay_id is not None:
                replay = uow.forecasts.get_goal(replay_id)
                if replay is None:
                    raise RuntimeError("idempotency record points to a missing goal")
                return replay
            self._validate_goal_account(uow, goal)
            uow.forecasts.add_goal(goal)
            self._audit(
                uow,
                actor_id,
                "goal.created",
                "financial_goal",
                goal.id,
                request_id,
                {"currency": goal.target.currency.code, "priority": goal.priority},
            )
            self._remember(
                uow,
                goal.owner_id,
                "create_financial_goal",
                idempotency_key,
                request_hash,
                "financial_goal",
                goal.id,
            )
            uow.commit()
            return goal

    def update_goal(
        self,
        *,
        goal: FinancialGoal,
        actor_id: UUID,
        expected_version: int,
        request_id: UUID | None,
    ) -> FinancialGoal:
        if goal.owner_id != actor_id:
            raise OwnershipError("actor must own the financial goal")
        with self._uow_factory.open(goal.owner_id) as uow:
            previous = uow.forecasts.get_goal(goal.id)
            if previous is None or previous.archived:
                raise ResourceNotFoundError("financial goal was not found")
            self._validate_goal_account(uow, goal)
            saved = uow.forecasts.save_goal(goal, expected_version=expected_version)
            self._audit(
                uow,
                actor_id,
                "goal.updated",
                "financial_goal",
                goal.id,
                request_id,
                {
                    "previous_version": expected_version,
                    "version": saved.version,
                    "before": self._goal_snapshot(previous),
                    "after": self._goal_snapshot(saved),
                },
            )
            uow.commit()
            return saved

    def archive_goal(
        self,
        *,
        owner_id: UUID,
        actor_id: UUID,
        goal_id: UUID,
        expected_version: int,
        request_id: UUID | None,
    ) -> FinancialGoal:
        if owner_id != actor_id:
            raise OwnershipError("actor must own the financial goal")
        with self._uow_factory.open(owner_id) as uow:
            goal = uow.forecasts.get_goal(goal_id)
            if goal is None or goal.archived:
                raise ResourceNotFoundError("financial goal was not found")
            saved = uow.forecasts.save_goal(
                replace(goal, archived=True), expected_version=expected_version
            )
            self._audit(
                uow,
                actor_id,
                "goal.archived",
                "financial_goal",
                goal.id,
                request_id,
                {"previous_version": expected_version, "version": saved.version},
            )
            uow.commit()
            return saved

    @staticmethod
    def _goal_snapshot(goal: FinancialGoal) -> dict[str, object]:
        return {
            "name": goal.name,
            "target": str(goal.target.amount),
            "currency": goal.target.currency.code,
            "saved_amount": str(goal.saved_amount.amount),
            "target_date": goal.target_date.isoformat(),
            "priority": goal.priority,
            "linked_account_id": None
            if goal.linked_account_id is None
            else str(goal.linked_account_id),
            "archived": goal.archived,
            "version": goal.version,
        }

    def list_goals(self, owner_id: UUID) -> tuple[FinancialGoal, ...]:
        with self._uow_factory.open(owner_id) as uow:
            return uow.forecasts.list_goals()

    def get_goal(self, owner_id: UUID, goal_id: UUID) -> FinancialGoal:
        with self._uow_factory.open(owner_id) as uow:
            goal = uow.forecasts.get_goal(goal_id)
            if goal is None or goal.archived:
                raise ResourceNotFoundError("financial goal was not found")
            return goal

    def run(
        self,
        *,
        owner_id: UUID,
        timezone: str,
        currency: Currency,
        horizon: date | None,
        scenario_id: UUID | None,
    ) -> tuple[ForecastResult, GoalPlanResult]:
        captured_at = self._clock()
        with self._uow_factory.open(owner_id) as uow:
            assumptions = self._resolve_assumptions(
                uow, currency=currency, horizon=horizon, scenario_id=scenario_id
            )
            snapshot = self._build_snapshot(
                uow,
                owner_id=owner_id,
                captured_at=captured_at,
                timezone=timezone,
                currency=currency,
                through=assumptions.horizon,
            )
            goals = uow.forecasts.list_goals()
        result = forecast_finances(snapshot, assumptions)
        return result, plan_goals(result, goals)

    def compare(
        self,
        *,
        owner_id: UUID,
        timezone: str,
        currency: Currency,
        baseline_horizon: date,
        scenario_ids: tuple[UUID, ...],
    ) -> ForecastComparison:
        captured_at = self._clock()
        with self._uow_factory.open(owner_id) as uow:
            scenarios: list[ForecastScenario] = []
            for scenario_id in scenario_ids:
                scenario = uow.forecasts.get_scenario(scenario_id)
                if scenario is None:
                    raise ResourceNotFoundError("forecast scenario was not found")
                if scenario.currency != currency:
                    raise ResourceConflictError(
                        "scenario currency differs from comparison currency"
                    )
                scenarios.append(scenario)
            max_horizon = max((baseline_horizon, *(item.assumptions.horizon for item in scenarios)))
            snapshot = self._build_snapshot(
                uow,
                owner_id=owner_id,
                captured_at=captured_at,
                timezone=timezone,
                currency=currency,
                through=max_horizon,
            )
            goals = uow.forecasts.list_goals()
        variants = [
            (None, "Baseline", ForecastAssumptions(horizon=baseline_horizon)),
            *[(item.id, item.name, item.assumptions) for item in scenarios],
        ]
        items = []
        for variant_id, name, assumptions in variants:
            result = forecast_finances(snapshot, assumptions)
            items.append(
                ForecastComparisonItem(
                    scenario_id=variant_id,
                    scenario_name=name,
                    forecast=result,
                    goal_plan=plan_goals(result, goals),
                )
            )
        return ForecastComparison(snapshot.snapshot_id, tuple(items))

    @staticmethod
    def _resolve_assumptions(
        uow: UnitOfWork,
        *,
        currency: Currency,
        horizon: date | None,
        scenario_id: UUID | None,
    ) -> ForecastAssumptions:
        if scenario_id is None:
            if horizon is None:
                raise ValueError("baseline forecast requires a horizon")
            return ForecastAssumptions(horizon=horizon)
        scenario = uow.forecasts.get_scenario(scenario_id)
        if scenario is None:
            raise ResourceNotFoundError("forecast scenario was not found")
        if scenario.currency != currency:
            raise ResourceConflictError("scenario currency differs from forecast currency")
        if horizon is not None and horizon != scenario.assumptions.horizon:
            raise ResourceConflictError("scenario horizon is stored in its assumptions")
        return scenario.assumptions

    def _build_snapshot(
        self,
        uow: UnitOfWork,
        *,
        owner_id: UUID,
        captured_at: Instant,
        timezone: str,
        currency: Currency,
        through: date,
    ) -> ForecastInputSnapshot:
        zone = ZoneInfo(timezone)
        as_of = captured_at.value.astimezone(zone).date()
        accounts = tuple(
            item
            for item in uow.ledger.list_accounts(include_archived=True)
            if item.kind.is_asset and item.currency == currency
        )
        transactions = uow.ledger.list_analytics_transactions(captured_at.value)
        balances = _balances(accounts, transactions, captured_at.value)
        snapshot_accounts = tuple(
            ForecastAccount(
                id=item.id,
                name=item.name,
                kind=item.kind.value,
                opening_balance=Money.of(balances[item.id], currency),
                interest_bearing=False,
            )
            for item in sorted(accounts, key=lambda value: str(value.id))
        )
        history_periods = _complete_history_periods(transactions, zone, as_of)
        history = _historical_expenses(
            accounts,
            transactions,
            history_periods,
            zone,
            currency,
        )
        scheduled = list(
            _recurring_cashflows(
                uow.forecasts.list_recurring_rules(),
                as_of,
                through,
                currency,
            )
        )
        scheduled.extend(_deposit_cashflows(uow, as_of, through, currency))
        return ForecastInputSnapshot(
            owner_id=owner_id,
            captured_at=captured_at,
            as_of=as_of,
            timezone=timezone,
            currency=currency,
            accounts=snapshot_accounts,
            scheduled_cashflows=tuple(
                sorted(
                    scheduled,
                    key=lambda item: (item.occurs_on, item.event_id, str(item.account_id)),
                )
            ),
            history_periods=history_periods,
            historical_expenses=history,
        )

    @staticmethod
    def _validate_scenario_accounts(uow: UnitOfWork, scenario: ForecastScenario) -> None:
        for cashflow in scenario.assumptions.one_time_cashflows:
            account = uow.ledger.get_account(cashflow.account_id)
            if account is None or not account.kind.is_asset:
                raise ResourceNotFoundError("scenario cashflow account was not found")
            if account.currency != scenario.currency:
                raise ResourceConflictError("scenario cashflow account currency differs")

    @staticmethod
    def _validate_goal_account(uow: UnitOfWork, goal: FinancialGoal) -> None:
        if goal.linked_account_id is None:
            return
        account = uow.ledger.get_account(goal.linked_account_id)
        if account is None or not account.kind.is_asset:
            raise ResourceNotFoundError("goal linked account was not found")
        if account.currency != goal.target.currency:
            raise ResourceConflictError("goal linked account currency differs")

    @staticmethod
    def _lock_and_replay(uow: UnitOfWork, scope: str, key: str, request_hash: str) -> UUID | None:
        uow.idempotency.lock(scope, key)
        existing = uow.idempotency.get(scope, key)
        if existing is None:
            return None
        if existing.request_hash != request_hash:
            raise IdempotencyConflictError(
                "idempotency key was used with a different request payload"
            )
        return existing.resource_id

    def _remember(
        self,
        uow: UnitOfWork,
        owner_id: UUID,
        scope: str,
        key: str,
        request_hash: str,
        resource_type: str,
        resource_id: UUID,
    ) -> None:
        uow.idempotency.add(
            IdempotencyRecord(
                owner_id=owner_id,
                scope=scope,
                key=key,
                request_hash=request_hash,
                resource_type=resource_type,
                resource_id=resource_id,
                created_at=self._clock(),
            )
        )

    def _audit(
        self,
        uow: UnitOfWork,
        actor_id: UUID,
        event_type: str,
        aggregate_type: str,
        aggregate_id: UUID,
        request_id: UUID | None,
        payload: dict[str, object],
    ) -> None:
        uow.audit.append(
            AuditEvent(
                id=self._uuid_factory(),
                owner_id=uow.ledger.owner_id,
                actor_id=actor_id,
                event_type=event_type,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                occurred_at=self._clock(),
                request_id=request_id,
                payload=payload,
            )
        )


def _balances(
    accounts: tuple[Account, ...],
    transactions: tuple[Transaction, ...],
    captured_at: datetime,
) -> dict[UUID, Decimal]:
    result = {item.id: Decimal("0") for item in accounts}
    for transaction in transactions:
        if transaction.occurred_at.value >= captured_at:
            continue
        for posting in transaction.postings:
            if posting.account_id in result:
                result[posting.account_id] += posting.amount.amount
    return result


def _complete_history_periods(
    transactions: tuple[Transaction, ...], zone: ZoneInfo, as_of: date
) -> tuple[date, ...]:
    if not transactions:
        return ()
    earliest = min(item.occurred_at.value.astimezone(zone).date() for item in transactions)
    first = _next_month(date(earliest.year, earliest.month, 1))
    current = date(as_of.year, as_of.month, 1)
    values: list[date] = []
    cursor = first
    while cursor < current:
        values.append(cursor)
        cursor = _next_month(cursor)
    return tuple(values[-HISTORY_MONTHS:])


def _historical_expenses(
    accounts: tuple[Account, ...],
    transactions: tuple[Transaction, ...],
    periods: tuple[date, ...],
    zone: ZoneInfo,
    currency: Currency,
) -> tuple[HistoricalExpenseSample, ...]:
    account_ids = {item.id for item in accounts}
    by_id = {item.id: item for item in transactions}
    values: defaultdict[tuple[date, UUID], Decimal] = defaultdict(Decimal)
    period_set = set(periods)
    for transaction in transactions:
        effective = transaction
        if transaction.kind is TransactionKind.REVERSAL:
            if transaction.reversal_of_id is None:
                continue
            original = by_id.get(transaction.reversal_of_id)
            if original is None:
                continue
            effective = original
        if effective.kind is not TransactionKind.EXPENSE or effective.source == "recurring":
            continue
        local_date = transaction.occurred_at.value.astimezone(zone).date()
        period = date(local_date.year, local_date.month, 1)
        if period not in period_set:
            continue
        for posting in transaction.postings:
            if posting.account_id in account_ids:
                values[(period, posting.account_id)] += -posting.amount.amount
    return tuple(
        HistoricalExpenseSample(
            period_start=period,
            account_id=account.id,
            amount=Money.of(max(values[(period, account.id)], Decimal("0")), currency),
        )
        for period in periods
        for account in sorted(accounts, key=lambda item: str(item.id))
    )


def _recurring_cashflows(
    rules: tuple[RecurringRule, ...],
    as_of: date,
    through: date,
    currency: Currency,
) -> tuple[ForecastCashflow, ...]:
    result: list[ForecastCashflow] = []
    for rule in rules:
        if rule.status is not RecurringRuleStatus.ACTIVE or rule.next_occurrence_at is None:
            continue
        if rule.operation.amount.currency != currency:
            continue
        occurrence: Instant | None = rule.next_occurrence_at
        count = 0
        while occurrence is not None:
            local_date = occurrence.value.astimezone(ZoneInfo(rule.timezone)).date()
            if local_date > through:
                break
            occurs_on = max(local_date, as_of)
            event = f"recurring:{rule.id}:{occurrence.value.isoformat()}"
            operation = rule.operation
            if operation.kind is TransactionKind.INCOME:
                result.append(
                    ForecastCashflow(
                        event,
                        occurs_on,
                        operation.account_id,
                        operation.amount,
                        ForecastFlowKind.INCOME,
                    )
                )
            elif operation.kind is TransactionKind.EXPENSE:
                result.append(
                    ForecastCashflow(
                        event,
                        occurs_on,
                        operation.account_id,
                        -operation.amount,
                        ForecastFlowKind.EXPENSE,
                    )
                )
            else:
                assert operation.destination_account_id is not None
                result.extend(
                    (
                        ForecastCashflow(
                            f"{event}:source",
                            occurs_on,
                            operation.account_id,
                            -operation.amount,
                            ForecastFlowKind.TRANSFER,
                        ),
                        ForecastCashflow(
                            f"{event}:destination",
                            occurs_on,
                            operation.destination_account_id,
                            operation.amount,
                            ForecastFlowKind.TRANSFER,
                        ),
                    )
                )
            occurrence = next_occurrence(rule, occurrence)
            count += 1
            if count > 10000:
                raise RuntimeError("recurring forecast exceeded its safety limit")
    return tuple(result)


def _deposit_cashflows(
    uow: UnitOfWork,
    as_of: date,
    through: date,
    currency: Currency,
) -> tuple[ForecastCashflow, ...]:
    result: list[ForecastCashflow] = []
    for terms in uow.deposits.list():
        if terms.currency != currency or not terms.opened_on <= as_of < terms.matures_on:
            continue
        transactions = uow.ledger.list_deposit_transactions(terms.id)
        projection = project_deposit(terms, principal_cashflows(terms, transactions), as_of=as_of)
        for index, entry in enumerate(projection.schedule):
            if as_of < entry.posting_date <= through and entry.net_interest.amount != 0:
                result.append(
                    ForecastCashflow(
                        event_id=f"deposit:{terms.id}:{entry.posting_date.isoformat()}:{index}",
                        occurs_on=entry.posting_date,
                        account_id=terms.principal_account_id,
                        amount=entry.net_interest,
                        kind=ForecastFlowKind.DEPOSIT_INTEREST,
                    )
                )
    return tuple(result)


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)
