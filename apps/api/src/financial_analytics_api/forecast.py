from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from financial_analytics_api.deposits import RateInput
from financial_analytics_api.errors import ProblemDetails
from financial_analytics_api.identity import Authenticated
from financial_analytics_api.ledger import (
    IdempotencyKey,
    MoneyInput,
    MoneyResponse,
    MutatingSession,
    _money_response,
    _request_id,
)
from financial_analytics_app import ForecastComparison, ForecastService
from financial_analytics_domain import (
    AccountForecast,
    BaselineExpense,
    Currency,
    FinancialGoal,
    ForecastAssumptions,
    ForecastMonth,
    ForecastResult,
    ForecastScenario,
    GoalPlan,
    GoalPlanResult,
    OneTimeCashflow,
)
from financial_analytics_domain.errors import DomainError

router = APIRouter(prefix="/api/v1", tags=["forecast"])


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OneTimeCashflowInput(ApiModel):
    occurs_on: date
    account_id: UUID
    money: MoneyInput
    description: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def reject_zero(self) -> OneTimeCashflowInput:
        if Decimal(self.money.amount) == 0:
            raise ValueError("one-time cashflow must not be zero")
        return self


class ScenarioInput(ApiModel):
    name: str = Field(min_length=1, max_length=160)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    horizon: date
    income_change: RateInput = RateInput(value="0")
    expense_change: RateInput = RateInput(value="0")
    annual_inflation: RateInput = RateInput(value="0")
    annual_interest: RateInput = RateInput(value="0")
    one_time_cashflows: list[OneTimeCashflowInput] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_cashflow_currencies(self) -> ScenarioInput:
        if any(item.money.currency != self.currency for item in self.one_time_cashflows):
            raise ValueError("one-time cashflow currency must match scenario currency")
        return self


class UpdateScenarioRequest(ScenarioInput):
    version: int = Field(ge=1)


class OneTimeCashflowResponse(ApiModel):
    occurs_on: date
    account_id: UUID
    money: MoneyResponse
    description: str


class ScenarioResponse(ApiModel):
    id: UUID
    name: str
    currency: str
    horizon: date
    income_change: str
    expense_change: str
    annual_inflation: str
    annual_interest: str
    one_time_cashflows: list[OneTimeCashflowResponse]
    assumptions_version: str
    version: int


class GoalInput(ApiModel):
    name: str = Field(min_length=1, max_length=160)
    target: MoneyInput
    target_date: date
    saved_amount: MoneyInput
    priority: int = Field(ge=1, le=1000000)
    linked_account_id: UUID | None = None

    @model_validator(mode="after")
    def validate_money(self) -> GoalInput:
        if self.target.currency != self.saved_amount.currency:
            raise ValueError("goal target and saved amount currencies must match")
        if Decimal(self.target.amount) <= 0:
            raise ValueError("goal target must be positive")
        if Decimal(self.saved_amount.amount) < 0:
            raise ValueError("goal saved amount must not be negative")
        return self


class UpdateGoalRequest(GoalInput):
    version: int = Field(ge=1)


class ArchiveGoalRequest(ApiModel):
    version: int = Field(ge=1)


class GoalResponse(ApiModel):
    id: UUID
    name: str
    target: MoneyResponse
    target_date: date
    saved_amount: MoneyResponse
    priority: int
    linked_account_id: UUID | None
    version: int
    archived: bool


class AccountForecastResponse(ApiModel):
    account_id: UUID
    name: str
    opening_balance: MoneyResponse
    closing_balance: MoneyResponse


class BaselineExpenseResponse(ApiModel):
    account_id: UUID
    monthly_median: MoneyResponse
    observed_minimum: MoneyResponse
    observed_maximum: MoneyResponse
    sample_count: int


class ForecastMonthResponse(ApiModel):
    starts_on: date
    ends_on: date
    opening_total: MoneyResponse
    scheduled_income: MoneyResponse
    scheduled_expense: MoneyResponse
    irregular_expense: MoneyResponse
    deposit_interest: MoneyResponse
    savings_interest: MoneyResponse
    one_time_net: MoneyResponse
    net_change: MoneyResponse
    closing_total: MoneyResponse
    uncertainty_low: MoneyResponse
    uncertainty_high: MoneyResponse
    accounts: list[AccountForecastResponse]


class ForecastAssumptionsResponse(ApiModel):
    version: str
    horizon: date
    income_change: str
    expense_change: str
    annual_inflation: str
    annual_interest: str
    one_time_cashflows: list[OneTimeCashflowResponse]


class ForecastResponse(ApiModel):
    snapshot_id: str
    algorithm_version: str
    assumptions: ForecastAssumptionsResponse
    uncertainty_method: str
    uncertainty_explanation: str
    baseline_expenses: list[BaselineExpenseResponse]
    warnings: list[str]
    timeline: list[ForecastMonthResponse]
    accounts: list[AccountForecastResponse]
    opening_total: MoneyResponse
    final_total: MoneyResponse
    uncertainty_low: MoneyResponse
    uncertainty_high: MoneyResponse


class GoalPlanResponse(ApiModel):
    goal_id: UUID
    name: str
    priority: int
    linked_account_id: UUID | None
    target: MoneyResponse
    target_date: date
    saved_amount: MoneyResponse
    remaining_amount: MoneyResponse
    required_monthly_contribution: MoneyResponse
    average_available_monthly: MoneyResponse
    contribution_gap: MoneyResponse
    allocated_through_target: MoneyResponse
    projected_saved_at_target: MoneyResponse
    expected_completion_date: date | None
    shortfall: MoneyResponse
    feasible_by_target: bool
    status: str


class GoalPlanResultResponse(ApiModel):
    allocation_version: str
    allocation_explanation: str
    forecast_snapshot_id: str
    currency: str
    warnings: list[str]
    goals: list[GoalPlanResponse]


class ForecastRunResponse(ApiModel):
    forecast: ForecastResponse
    goal_plan: GoalPlanResultResponse
    disclaimer: str


class CompareForecastsRequest(ApiModel):
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    baseline_horizon: date
    scenario_ids: list[UUID] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_scenarios(self) -> CompareForecastsRequest:
        if len(self.scenario_ids) != len(set(self.scenario_ids)):
            raise ValueError("scenario_ids must be unique")
        return self


class ForecastComparisonItemResponse(ApiModel):
    scenario_id: UUID | None
    scenario_name: str
    forecast: ForecastResponse
    goal_plan: GoalPlanResultResponse


class ForecastComparisonResponse(ApiModel):
    snapshot_id: str
    items: list[ForecastComparisonItemResponse]
    disclaimer: str


def _service(request: Request) -> ForecastService:
    return request.app.state.forecast_service  # type: ignore[no-any-return]


def _request_hash(payload: BaseModel, *, context: str) -> str:
    encoded = json.dumps(
        {"context": context, "payload": payload.model_dump(mode="json")},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _problem_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    return {
        code: {
            "model": ProblemDetails,
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ProblemDetails"}
                }
            },
        }
        for code in status_codes
    }


@router.post(
    "/forecast-scenarios",
    operation_id="createForecastScenario",
    status_code=status.HTTP_201_CREATED,
    response_model=ScenarioResponse,
    responses=_problem_responses(401, 403, 409, 422),
)
def create_scenario(
    payload: ScenarioInput,
    request: Request,
    authenticated: MutatingSession,
    idempotency_key: IdempotencyKey,
) -> ScenarioResponse:
    scenario = _scenario_domain(payload, authenticated.profile.id, uuid4(), 1)
    saved = _service(request).create_scenario(
        scenario=scenario,
        actor_id=authenticated.profile.id,
        idempotency_key=idempotency_key,
        request_hash=_request_hash(payload, context="create_forecast_scenario"),
        request_id=_request_id(request),
    )
    return _scenario_response(saved)


@router.get(
    "/forecast-scenarios",
    operation_id="listForecastScenarios",
    response_model=list[ScenarioResponse],
    responses=_problem_responses(401),
)
def list_scenarios(request: Request, authenticated: Authenticated) -> list[ScenarioResponse]:
    return [
        _scenario_response(item)
        for item in _service(request).list_scenarios(authenticated.profile.id)
    ]


@router.get(
    "/forecast-scenarios/{scenario_id}",
    operation_id="getForecastScenario",
    response_model=ScenarioResponse,
    responses=_problem_responses(401, 404),
)
def get_scenario(
    scenario_id: UUID, request: Request, authenticated: Authenticated
) -> ScenarioResponse:
    return _scenario_response(_service(request).get_scenario(authenticated.profile.id, scenario_id))


@router.put(
    "/forecast-scenarios/{scenario_id}",
    operation_id="updateForecastScenario",
    response_model=ScenarioResponse,
    responses=_problem_responses(401, 403, 404, 409, 422),
)
def update_scenario(
    scenario_id: UUID,
    payload: UpdateScenarioRequest,
    request: Request,
    authenticated: MutatingSession,
) -> ScenarioResponse:
    scenario = _scenario_domain(payload, authenticated.profile.id, scenario_id, payload.version)
    return _scenario_response(
        _service(request).update_scenario(
            scenario=scenario,
            actor_id=authenticated.profile.id,
            expected_version=payload.version,
            request_id=_request_id(request),
        )
    )


@router.post(
    "/goals",
    operation_id="createFinancialGoal",
    status_code=status.HTTP_201_CREATED,
    response_model=GoalResponse,
    responses=_problem_responses(401, 403, 409, 422),
)
def create_goal(
    payload: GoalInput,
    request: Request,
    authenticated: MutatingSession,
    idempotency_key: IdempotencyKey,
) -> GoalResponse:
    goal = _goal_domain(payload, authenticated.profile.id, uuid4(), 1)
    saved = _service(request).create_goal(
        goal=goal,
        actor_id=authenticated.profile.id,
        idempotency_key=idempotency_key,
        request_hash=_request_hash(payload, context="create_financial_goal"),
        request_id=_request_id(request),
    )
    return _goal_response(saved)


@router.get(
    "/goals",
    operation_id="listFinancialGoals",
    response_model=list[GoalResponse],
    responses=_problem_responses(401),
)
def list_goals(request: Request, authenticated: Authenticated) -> list[GoalResponse]:
    return [_goal_response(item) for item in _service(request).list_goals(authenticated.profile.id)]


@router.get(
    "/goals/{goal_id}",
    operation_id="getFinancialGoal",
    response_model=GoalResponse,
    responses=_problem_responses(401, 404),
)
def get_goal(goal_id: UUID, request: Request, authenticated: Authenticated) -> GoalResponse:
    return _goal_response(_service(request).get_goal(authenticated.profile.id, goal_id))


@router.put(
    "/goals/{goal_id}",
    operation_id="updateFinancialGoal",
    response_model=GoalResponse,
    responses=_problem_responses(401, 403, 404, 409, 422),
)
def update_goal(
    goal_id: UUID,
    payload: UpdateGoalRequest,
    request: Request,
    authenticated: MutatingSession,
) -> GoalResponse:
    goal = _goal_domain(payload, authenticated.profile.id, goal_id, payload.version)
    return _goal_response(
        _service(request).update_goal(
            goal=goal,
            actor_id=authenticated.profile.id,
            expected_version=payload.version,
            request_id=_request_id(request),
        )
    )


@router.delete(
    "/goals/{goal_id}",
    operation_id="archiveFinancialGoal",
    response_model=GoalResponse,
    responses=_problem_responses(401, 403, 404, 409),
)
def archive_goal(
    goal_id: UUID,
    payload: ArchiveGoalRequest,
    request: Request,
    authenticated: MutatingSession,
) -> GoalResponse:
    return _goal_response(
        _service(request).archive_goal(
            owner_id=authenticated.profile.id,
            actor_id=authenticated.profile.id,
            goal_id=goal_id,
            expected_version=payload.version,
            request_id=_request_id(request),
        )
    )


@router.get(
    "/forecasts",
    operation_id="getForecast",
    response_model=ForecastRunResponse,
    responses=_problem_responses(401, 404, 409, 422),
)
def get_forecast(
    request: Request,
    authenticated: Authenticated,
    currency: Annotated[str, Query(pattern=r"^[A-Z]{3}$")],
    through: Annotated[date | None, Query()] = None,
    scenario_id: Annotated[UUID | None, Query()] = None,
) -> ForecastRunResponse:
    if scenario_id is None and through is None:
        raise DomainError("baseline forecast requires the through query parameter")
    forecast, goals = _service(request).run(
        owner_id=authenticated.profile.id,
        timezone=authenticated.profile.timezone,
        currency=Currency(currency),
        horizon=through,
        scenario_id=scenario_id,
    )
    return ForecastRunResponse(
        forecast=_forecast_response(forecast),
        goal_plan=_goal_plan_result_response(goals),
        disclaimer=_disclaimer(),
    )


@router.post(
    "/forecasts/compare",
    operation_id="compareForecastScenarios",
    response_model=ForecastComparisonResponse,
    responses=_problem_responses(401, 404, 409, 422),
)
def compare_forecasts(
    payload: CompareForecastsRequest,
    request: Request,
    authenticated: Authenticated,
) -> ForecastComparisonResponse:
    comparison = _service(request).compare(
        owner_id=authenticated.profile.id,
        timezone=authenticated.profile.timezone,
        currency=Currency(payload.currency),
        baseline_horizon=payload.baseline_horizon,
        scenario_ids=tuple(payload.scenario_ids),
    )
    return _comparison_response(comparison)


def _scenario_domain(
    payload: ScenarioInput, owner_id: UUID, scenario_id: UUID, version: int
) -> ForecastScenario:
    currency = Currency(payload.currency)
    return ForecastScenario(
        id=scenario_id,
        owner_id=owner_id,
        name=payload.name,
        currency=currency,
        assumptions=ForecastAssumptions(
            horizon=payload.horizon,
            income_change=payload.income_change.to_domain(),
            expense_change=payload.expense_change.to_domain(),
            annual_inflation=payload.annual_inflation.to_domain(),
            annual_interest=payload.annual_interest.to_domain(),
            one_time_cashflows=tuple(
                OneTimeCashflow(
                    occurs_on=item.occurs_on,
                    account_id=item.account_id,
                    amount=item.money.to_domain(),
                    description=item.description,
                )
                for item in payload.one_time_cashflows
            ),
        ),
        version=version,
    )


def _goal_domain(payload: GoalInput, owner_id: UUID, goal_id: UUID, version: int) -> FinancialGoal:
    return FinancialGoal(
        id=goal_id,
        owner_id=owner_id,
        name=payload.name,
        target=payload.target.to_domain(),
        target_date=payload.target_date,
        saved_amount=payload.saved_amount.to_domain(),
        priority=payload.priority,
        linked_account_id=payload.linked_account_id,
        version=version,
    )


def _scenario_response(item: ForecastScenario) -> ScenarioResponse:
    assumptions = item.assumptions
    return ScenarioResponse(
        id=item.id,
        name=item.name,
        currency=item.currency.code,
        horizon=assumptions.horizon,
        income_change=_decimal(assumptions.income_change.value),
        expense_change=_decimal(assumptions.expense_change.value),
        annual_inflation=_decimal(assumptions.annual_inflation.value),
        annual_interest=_decimal(assumptions.annual_interest.value),
        one_time_cashflows=[_one_time_response(value) for value in assumptions.one_time_cashflows],
        assumptions_version=assumptions.version,
        version=item.version,
    )


def _goal_response(item: FinancialGoal) -> GoalResponse:
    return GoalResponse(
        id=item.id,
        name=item.name,
        target=_money_response(item.target),
        target_date=item.target_date,
        saved_amount=_money_response(item.saved_amount),
        priority=item.priority,
        linked_account_id=item.linked_account_id,
        version=item.version,
        archived=item.archived,
    )


def _forecast_response(item: ForecastResult) -> ForecastResponse:
    assumptions = item.assumptions
    return ForecastResponse(
        snapshot_id=item.snapshot_id,
        algorithm_version=item.algorithm_version,
        assumptions=ForecastAssumptionsResponse(
            version=assumptions.version,
            horizon=assumptions.horizon,
            income_change=_decimal(assumptions.income_change.value),
            expense_change=_decimal(assumptions.expense_change.value),
            annual_inflation=_decimal(assumptions.annual_inflation.value),
            annual_interest=_decimal(assumptions.annual_interest.value),
            one_time_cashflows=[
                _one_time_response(value) for value in assumptions.one_time_cashflows
            ],
        ),
        uncertainty_method=item.uncertainty_method,
        uncertainty_explanation=item.uncertainty_explanation,
        baseline_expenses=[_baseline_response(value) for value in item.baseline_expenses],
        warnings=list(item.warnings),
        timeline=[_month_response(value) for value in item.timeline],
        accounts=[_account_response(value) for value in item.accounts],
        opening_total=_money_response(item.opening_total),
        final_total=_money_response(item.final_total),
        uncertainty_low=_money_response(item.uncertainty_low),
        uncertainty_high=_money_response(item.uncertainty_high),
    )


def _month_response(item: ForecastMonth) -> ForecastMonthResponse:
    return ForecastMonthResponse(
        starts_on=item.starts_on,
        ends_on=item.ends_on,
        opening_total=_money_response(item.opening_total),
        scheduled_income=_money_response(item.scheduled_income),
        scheduled_expense=_money_response(item.scheduled_expense),
        irregular_expense=_money_response(item.irregular_expense),
        deposit_interest=_money_response(item.deposit_interest),
        savings_interest=_money_response(item.savings_interest),
        one_time_net=_money_response(item.one_time_net),
        net_change=_money_response(item.net_change),
        closing_total=_money_response(item.closing_total),
        uncertainty_low=_money_response(item.uncertainty_low),
        uncertainty_high=_money_response(item.uncertainty_high),
        accounts=[_account_response(value) for value in item.accounts],
    )


def _account_response(item: AccountForecast) -> AccountForecastResponse:
    return AccountForecastResponse(
        account_id=item.account_id,
        name=item.name,
        opening_balance=_money_response(item.opening_balance),
        closing_balance=_money_response(item.closing_balance),
    )


def _baseline_response(item: BaselineExpense) -> BaselineExpenseResponse:
    return BaselineExpenseResponse(
        account_id=item.account_id,
        monthly_median=_money_response(item.monthly_median),
        observed_minimum=_money_response(item.observed_minimum),
        observed_maximum=_money_response(item.observed_maximum),
        sample_count=item.sample_count,
    )


def _goal_plan_result_response(item: GoalPlanResult) -> GoalPlanResultResponse:
    return GoalPlanResultResponse(
        allocation_version=item.allocation_version,
        allocation_explanation=item.allocation_explanation,
        forecast_snapshot_id=item.forecast_snapshot_id,
        currency=item.currency.code,
        warnings=list(item.warnings),
        goals=[_goal_plan_response(value) for value in item.goals],
    )


def _goal_plan_response(item: GoalPlan) -> GoalPlanResponse:
    return GoalPlanResponse(
        goal_id=item.goal_id,
        name=item.name,
        priority=item.priority,
        linked_account_id=item.linked_account_id,
        target=_money_response(item.target),
        target_date=item.target_date,
        saved_amount=_money_response(item.saved_amount),
        remaining_amount=_money_response(item.remaining_amount),
        required_monthly_contribution=_money_response(item.required_monthly_contribution),
        average_available_monthly=_money_response(item.average_available_monthly),
        contribution_gap=_money_response(item.contribution_gap),
        allocated_through_target=_money_response(item.allocated_through_target),
        projected_saved_at_target=_money_response(item.projected_saved_at_target),
        expected_completion_date=item.expected_completion_date,
        shortfall=_money_response(item.shortfall),
        feasible_by_target=item.feasible_by_target,
        status=item.status,
    )


def _comparison_response(item: ForecastComparison) -> ForecastComparisonResponse:
    return ForecastComparisonResponse(
        snapshot_id=item.snapshot_id,
        items=[
            ForecastComparisonItemResponse(
                scenario_id=value.scenario_id,
                scenario_name=value.scenario_name,
                forecast=_forecast_response(value.forecast),
                goal_plan=_goal_plan_result_response(value.goal_plan),
            )
            for value in item.items
        ],
        disclaimer=_disclaimer(),
    )


def _one_time_response(item: OneTimeCashflow) -> OneTimeCashflowResponse:
    return OneTimeCashflowResponse(
        occurs_on=item.occurs_on,
        account_id=item.account_id,
        money=_money_response(item.amount),
        description=item.description,
    )


def _decimal(value: Decimal) -> str:
    return format(value, "f")


def _disclaimer() -> str:
    return (
        "This is a deterministic financial forecast based on stated assumptions and historical "
        "data, not a guarantee of future balances or goal completion."
    )
