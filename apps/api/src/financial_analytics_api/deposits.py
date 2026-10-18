from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from financial_analytics_api.errors import ProblemDetails
from financial_analytics_api.identity import Authenticated
from financial_analytics_api.ledger import (
    IdempotencyKey,
    MoneyInput,
    MoneyResponse,
    MutatingSession,
    TransactionResponse,
    _money_response,
    _request_id,
    _transaction_response,
)
from financial_analytics_app import DepositService, DepositValuation
from financial_analytics_domain import (
    DEPOSIT_ALGORITHM_VERSION,
    CapitalizationFrequency,
    Currency,
    DayCountConvention,
    DepositRatePeriod,
    DepositTerms,
    EarlyClosePolicy,
    EarlyCloseRule,
    Instant,
    InterestRoundingFrequency,
    Rate,
    RoundingPolicy,
)

router = APIRouter(prefix="/api/v1/deposits", tags=["deposits"])


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RateInput(ApiModel):
    value: str = Field(pattern=r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$", examples=["0.125"])

    @field_validator("value", mode="before")
    @classmethod
    def reject_non_string_rate(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("rate must be a decimal string")
        return value

    def to_domain(self) -> Rate:
        return Rate.of(self.value)


class RatePeriodInput(ApiModel):
    starts_on: date
    ends_on: date
    nominal_rate: RateInput


class EarlyCloseRuleInput(ApiModel):
    policy: EarlyClosePolicy
    nominal_rate: RateInput | None

    @model_validator(mode="after")
    def validate_rate_shape(self) -> EarlyCloseRuleInput:
        if (self.policy is EarlyClosePolicy.REPRICE) != (self.nominal_rate is not None):
            raise ValueError("reprice requires nominal_rate and other policies forbid it")
        return self


class DepositTermsInput(ApiModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "name": "Резерв на год",
                    "opening_balance": {"amount": "100000.00", "currency": "RUB"},
                    "currency": "RUB",
                    "opened_on": "2026-10-13",
                    "matures_on": "2027-10-13",
                    "rate_periods": [
                        {
                            "starts_on": "2026-10-13",
                            "ends_on": "2027-10-13",
                            "nominal_rate": {"value": "0.12"},
                        }
                    ],
                    "capitalization_frequency": "monthly_calendar_end",
                    "day_count_convention": "actual_365_fixed",
                    "rounding_policy": "half_up",
                    "interest_rounding_frequency": "capitalization",
                    "timezone": "Europe/Saratov",
                    "cashflow_cutoff_time": "12:00:00",
                    "cashflow_cutoff_inclusive": True,
                    "early_close_rule": {
                        "policy": "reprice",
                        "nominal_rate": {"value": "0.01"},
                    },
                    "tax_rate": {"value": "0"},
                }
            ]
        },
    )

    name: str = Field(min_length=1, max_length=160)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    opened_on: date
    matures_on: date
    rate_periods: list[RatePeriodInput] = Field(min_length=1)
    capitalization_frequency: CapitalizationFrequency
    day_count_convention: DayCountConvention
    rounding_policy: RoundingPolicy
    interest_rounding_frequency: InterestRoundingFrequency
    timezone: str = Field(min_length=1, max_length=100)
    cashflow_cutoff_time: time
    cashflow_cutoff_inclusive: bool
    early_close_rule: EarlyCloseRuleInput
    tax_rate: RateInput
    automatic_interest: bool = True


class CreateDepositRequest(DepositTermsInput):
    opening_balance: MoneyInput

    @model_validator(mode="after")
    def validate_opening_balance(self) -> CreateDepositRequest:
        if self.opening_balance.currency != self.currency:
            raise ValueError("opening balance currency must match deposit currency")
        if Decimal(self.opening_balance.amount) < 0:
            raise ValueError("opening balance must not be negative")
        return self


class UpdateDepositRequest(DepositTermsInput):
    version: int = Field(ge=1)


class ArchiveDepositRequest(ApiModel):
    version: int = Field(ge=1)


class RatePeriodResponse(ApiModel):
    starts_on: date
    ends_on: date
    nominal_rate: str


class EarlyCloseRuleResponse(ApiModel):
    policy: EarlyClosePolicy
    nominal_rate: str | None


class DepositTermsResponse(ApiModel):
    id: UUID
    principal_account_id: UUID
    name: str
    currency: str
    opened_on: date
    matures_on: date
    rate_periods: list[RatePeriodResponse]
    capitalization_frequency: CapitalizationFrequency
    day_count_convention: DayCountConvention
    rounding_policy: RoundingPolicy
    interest_rounding_frequency: InterestRoundingFrequency
    timezone: str
    cashflow_cutoff_time: time
    cashflow_cutoff_inclusive: bool
    early_close_rule: EarlyCloseRuleResponse
    tax_rate: str
    algorithm_version: str
    archived: bool
    version: int
    automatic_interest: bool


class DepositCashflowRequest(ApiModel):
    counterparty_account_id: UUID
    money: MoneyInput
    occurred_at: datetime
    description: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_cashflow(self) -> DepositCashflowRequest:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must include an explicit UTC offset")
        if Decimal(self.money.amount) == 0:
            raise ValueError("deposit cashflow must be non-zero")
        return self


class DepositInterestRequest(ApiModel):
    money: MoneyInput
    occurred_at: datetime
    description: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_interest(self) -> DepositInterestRequest:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must include an explicit UTC offset")
        if Decimal(self.money.amount) == 0:
            raise ValueError("deposit interest must be non-zero")
        return self


class InterestScheduleEntryResponse(ApiModel):
    accrual_starts_on: date
    accrual_ends_on: date
    posting_date: date
    opening_balance: MoneyResponse
    cashflow: MoneyResponse
    gross_interest: MoneyResponse
    tax: MoneyResponse
    net_interest: MoneyResponse
    closing_balance: MoneyResponse


class InterestReconciliationResponse(ApiModel):
    posting_date: date
    planned_interest: MoneyResponse
    actual_interest: MoneyResponse
    variance: MoneyResponse


class DepositValuationResponse(ApiModel):
    algorithm_version: str
    as_of: date
    closes_on: date
    current_principal: MoneyResponse
    accrued_interest: MoneyResponse
    earned_interest: MoneyResponse
    ledger_balance: MoneyResponse
    current_value: MoneyResponse
    projected_maturity_value: MoneyResponse
    effective_yield: str | None
    schedule: list[InterestScheduleEntryResponse]
    reconciliation: list[InterestReconciliationResponse]


def _service(request: Request) -> DepositService:
    return request.app.state.deposit_service  # type: ignore[no-any-return]


def _request_hash(payload: BaseModel, *, context: str) -> str:
    encoded = json.dumps(
        {"context": context, "payload": payload.model_dump(mode="json")},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
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
    "",
    operation_id="createDeposit",
    response_model=DepositTermsResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_problem_responses(401, 403, 404, 409, 422),
)
def create_deposit(
    payload: CreateDepositRequest,
    request: Request,
    authenticated: MutatingSession,
    idempotency_key: IdempotencyKey,
) -> DepositTermsResponse:
    terms = DepositTerms(
        id=uuid4(),
        owner_id=authenticated.profile.id,
        principal_account_id=uuid4(),
        currency=Currency(payload.currency),
        opened_on=payload.opened_on,
        matures_on=payload.matures_on,
        rate_periods=tuple(
            DepositRatePeriod(item.starts_on, item.ends_on, item.nominal_rate.to_domain())
            for item in payload.rate_periods
        ),
        capitalization_frequency=payload.capitalization_frequency,
        day_count_convention=payload.day_count_convention,
        rounding_policy=payload.rounding_policy,
        interest_rounding_frequency=payload.interest_rounding_frequency,
        timezone=payload.timezone,
        cashflow_cutoff_time=payload.cashflow_cutoff_time,
        cashflow_cutoff_inclusive=payload.cashflow_cutoff_inclusive,
        early_close_rule=EarlyCloseRule(
            payload.early_close_rule.policy,
            None
            if payload.early_close_rule.nominal_rate is None
            else payload.early_close_rule.nominal_rate.to_domain(),
        ),
        tax_rate=payload.tax_rate.to_domain(),
        algorithm_version=DEPOSIT_ALGORITHM_VERSION,
        name=payload.name.strip(),
        automatic_interest=payload.automatic_interest,
    )
    saved = _service(request).create(
        terms=terms,
        actor_id=authenticated.profile.id,
        idempotency_key=idempotency_key,
        request_hash=_request_hash(payload, context="create_deposit"),
        request_id=_request_id(request),
        initial_balance=payload.opening_balance.to_domain(),
        opening_occurred_at=Instant(
            datetime.combine(payload.opened_on, time(12), tzinfo=ZoneInfo(payload.timezone))
        ),
    )
    return _terms_response(saved)


@router.get("", operation_id="listDeposits", response_model=list[DepositTermsResponse])
def list_deposits(request: Request, authenticated: Authenticated) -> list[DepositTermsResponse]:
    return [_terms_response(item) for item in _service(request).list(authenticated.profile.id)]


@router.get(
    "/{deposit_id}",
    operation_id="getDeposit",
    response_model=DepositTermsResponse,
    responses=_problem_responses(401, 404),
)
def get_deposit(
    deposit_id: UUID, request: Request, authenticated: Authenticated
) -> DepositTermsResponse:
    return _terms_response(_service(request).get(authenticated.profile.id, deposit_id))


@router.put(
    "/{deposit_id}",
    operation_id="updateDeposit",
    response_model=DepositTermsResponse,
    responses=_problem_responses(401, 403, 404, 409, 422),
)
def update_deposit(
    deposit_id: UUID,
    payload: UpdateDepositRequest,
    request: Request,
    authenticated: MutatingSession,
) -> DepositTermsResponse:
    previous = _service(request).get(authenticated.profile.id, deposit_id)
    terms = _terms_from_input(
        payload,
        owner_id=authenticated.profile.id,
        deposit_id=deposit_id,
        principal_account_id=previous.principal_account_id,
        version=payload.version,
    )
    return _terms_response(
        _service(request).update(
            terms=terms,
            actor_id=authenticated.profile.id,
            expected_version=payload.version,
            request_id=_request_id(request),
        )
    )


@router.delete(
    "/{deposit_id}",
    operation_id="archiveDeposit",
    response_model=DepositTermsResponse,
    responses=_problem_responses(401, 403, 404, 409),
)
def archive_deposit(
    deposit_id: UUID,
    payload: ArchiveDepositRequest,
    request: Request,
    authenticated: MutatingSession,
) -> DepositTermsResponse:
    return _terms_response(
        _service(request).archive(
            owner_id=authenticated.profile.id,
            actor_id=authenticated.profile.id,
            deposit_id=deposit_id,
            expected_version=payload.version,
            request_id=_request_id(request),
        )
    )


@router.post(
    "/{deposit_id}/cashflows",
    operation_id="recordDepositCashflow",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_problem_responses(401, 403, 404, 409, 422),
)
def record_deposit_cashflow(
    deposit_id: UUID,
    payload: DepositCashflowRequest,
    request: Request,
    authenticated: MutatingSession,
    idempotency_key: IdempotencyKey,
) -> TransactionResponse:
    transaction = _service(request).record_cashflow(
        owner_id=authenticated.profile.id,
        actor_id=authenticated.profile.id,
        deposit_id=deposit_id,
        counterparty_account_id=payload.counterparty_account_id,
        amount=payload.money.to_domain(),
        occurred_at=Instant(payload.occurred_at),
        description=payload.description,
        idempotency_key=idempotency_key,
        request_hash=_request_hash(payload, context=str(deposit_id)),
        request_id=_request_id(request),
    )
    return _transaction_response(transaction)


@router.post(
    "/{deposit_id}/interest-postings",
    operation_id="recordDepositInterest",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_problem_responses(401, 403, 404, 409, 422),
)
def record_deposit_interest(
    deposit_id: UUID,
    payload: DepositInterestRequest,
    request: Request,
    authenticated: MutatingSession,
    idempotency_key: IdempotencyKey,
) -> TransactionResponse:
    transaction = _service(request).record_interest(
        owner_id=authenticated.profile.id,
        actor_id=authenticated.profile.id,
        deposit_id=deposit_id,
        amount=payload.money.to_domain(),
        occurred_at=Instant(payload.occurred_at),
        description=payload.description,
        idempotency_key=idempotency_key,
        request_hash=_request_hash(payload, context=str(deposit_id)),
        request_id=_request_id(request),
    )
    return _transaction_response(transaction)


@router.get(
    "/{deposit_id}/valuation",
    operation_id="getDepositValuation",
    response_model=DepositValuationResponse,
    responses=_problem_responses(401, 404, 409, 422),
)
def get_deposit_valuation(
    deposit_id: UUID,
    request: Request,
    authenticated: Authenticated,
    as_of: Annotated[date, Query(description="Value at the start of this local calendar date.")],
    close_on: Annotated[date | None, Query()] = None,
) -> DepositValuationResponse:
    value = _service(request).valuation(
        authenticated.profile.id,
        deposit_id,
        as_of=as_of,
        close_on=close_on,
    )
    return _valuation_response(value)


def _terms_response(terms: DepositTerms) -> DepositTermsResponse:
    return DepositTermsResponse(
        id=terms.id,
        principal_account_id=terms.principal_account_id,
        name=terms.name,
        currency=terms.currency.code,
        opened_on=terms.opened_on,
        matures_on=terms.matures_on,
        rate_periods=[
            RatePeriodResponse(
                starts_on=period.starts_on,
                ends_on=period.ends_on,
                nominal_rate=_rate_string(period.nominal_rate),
            )
            for period in terms.rate_periods
        ],
        capitalization_frequency=terms.capitalization_frequency,
        day_count_convention=terms.day_count_convention,
        rounding_policy=terms.rounding_policy,
        interest_rounding_frequency=terms.interest_rounding_frequency,
        timezone=terms.timezone,
        cashflow_cutoff_time=terms.cashflow_cutoff_time,
        cashflow_cutoff_inclusive=terms.cashflow_cutoff_inclusive,
        early_close_rule=EarlyCloseRuleResponse(
            policy=terms.early_close_rule.policy,
            nominal_rate=(
                None
                if terms.early_close_rule.nominal_rate is None
                else _rate_string(terms.early_close_rule.nominal_rate)
            ),
        ),
        tax_rate=_rate_string(terms.tax_rate),
        algorithm_version=terms.algorithm_version,
        archived=terms.archived,
        version=terms.version,
        automatic_interest=terms.automatic_interest,
    )


def _terms_from_input(
    payload: DepositTermsInput,
    *,
    owner_id: UUID,
    deposit_id: UUID,
    principal_account_id: UUID,
    version: int,
) -> DepositTerms:
    return DepositTerms(
        id=deposit_id,
        owner_id=owner_id,
        principal_account_id=principal_account_id,
        currency=Currency(payload.currency),
        opened_on=payload.opened_on,
        matures_on=payload.matures_on,
        rate_periods=tuple(
            DepositRatePeriod(item.starts_on, item.ends_on, item.nominal_rate.to_domain())
            for item in payload.rate_periods
        ),
        capitalization_frequency=payload.capitalization_frequency,
        day_count_convention=payload.day_count_convention,
        rounding_policy=payload.rounding_policy,
        interest_rounding_frequency=payload.interest_rounding_frequency,
        timezone=payload.timezone,
        cashflow_cutoff_time=payload.cashflow_cutoff_time,
        cashflow_cutoff_inclusive=payload.cashflow_cutoff_inclusive,
        early_close_rule=EarlyCloseRule(
            payload.early_close_rule.policy,
            None
            if payload.early_close_rule.nominal_rate is None
            else payload.early_close_rule.nominal_rate.to_domain(),
        ),
        tax_rate=payload.tax_rate.to_domain(),
        algorithm_version=DEPOSIT_ALGORITHM_VERSION,
        name=payload.name.strip(),
        version=version,
        automatic_interest=payload.automatic_interest,
    )


def _rate_string(rate: Rate) -> str:
    value = format(rate.value, "f")
    if "." in value:
        value = value.rstrip("0").rstrip(".")
    return value or "0"


def _valuation_response(value: DepositValuation) -> DepositValuationResponse:
    projection = value.projection
    return DepositValuationResponse(
        algorithm_version=projection.algorithm_version,
        as_of=projection.as_of,
        closes_on=projection.closes_on,
        current_principal=_money_response(projection.current_principal),
        accrued_interest=_money_response(projection.accrued_interest),
        earned_interest=_money_response(value.earned_interest),
        ledger_balance=_money_response(value.ledger_balance),
        current_value=_money_response(projection.current_value),
        projected_maturity_value=_money_response(projection.projected_closing_value),
        effective_yield=(
            None if projection.effective_yield is None else _rate_string(projection.effective_yield)
        ),
        schedule=[
            InterestScheduleEntryResponse(
                accrual_starts_on=entry.accrual_starts_on,
                accrual_ends_on=entry.accrual_ends_on,
                posting_date=entry.posting_date,
                opening_balance=_money_response(entry.opening_balance),
                cashflow=_money_response(entry.cashflow),
                gross_interest=_money_response(entry.gross_interest),
                tax=_money_response(entry.tax),
                net_interest=_money_response(entry.net_interest),
                closing_balance=_money_response(entry.closing_balance),
            )
            for entry in projection.schedule
        ],
        reconciliation=[
            InterestReconciliationResponse(
                posting_date=row.posting_date,
                planned_interest=_money_response(row.planned_interest),
                actual_interest=_money_response(row.actual_interest),
                variance=_money_response(row.variance),
            )
            for row in value.reconciliation
        ],
    )
