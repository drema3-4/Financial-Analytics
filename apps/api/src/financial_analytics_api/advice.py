from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from financial_analytics_api.errors import ApplicationError, ProblemDetails
from financial_analytics_api.identity import Authenticated
from financial_analytics_app.advice import (
    AdviceContent,
    AdviceEvidence,
    AdviceOutcome,
    AdviceService,
)
from financial_analytics_domain import (
    AnalyticsPeriod,
    Currency,
    PeriodGranularity,
    default_period,
)

router = APIRouter(prefix="/api/v1", tags=["advice"])


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdviceRequest(ApiModel):
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    through: date | None = None
    scenario_id: UUID | None = None
    period_start: date | None = None
    period_end: date | None = None
    question: str | None = Field(default=None, min_length=1, max_length=2000)
    allow_external_user_text: bool = False

    @model_validator(mode="after")
    def validate_ranges(self) -> AdviceRequest:
        if self.scenario_id is None and self.through is None:
            raise ValueError("baseline advice requires through")
        if (self.period_start is None) != (self.period_end is None):
            raise ValueError("period_start and period_end must be supplied together")
        return self


class ProviderCapabilitiesResponse(ApiModel):
    json_schema: bool
    system_messages: bool
    non_thinking: bool


class AdviceProviderStatusResponse(ApiModel):
    status: str
    provider: str
    model: str | None
    endpoint_scope: str
    capabilities: ProviderCapabilitiesResponse
    prompt_version: str
    context_version: str


class AdvicePrivacyResponse(ApiModel):
    external_consent_default: bool = False
    external_user_text_shared: bool
    redactions_applied: int


class AdviceResponse(AdviceProviderStatusResponse):
    advice: AdviceContent | None
    evidence: list[AdviceEvidence]
    evidence_ids: list[str]
    error_code: str | None
    retry_after_seconds: int | None
    privacy: AdvicePrivacyResponse


def _service(request: Request) -> AdviceService:
    return request.app.state.advice_service  # type: ignore[no-any-return]


def _problem_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    return {
        code: {
            "model": ProblemDetails,
            "content": {"application/problem+json": {}},
        }
        for code in status_codes
    }


@router.get(
    "/advice/status",
    operation_id="getAdviceProviderStatus",
    response_model=AdviceProviderStatusResponse,
    responses=_problem_responses(401),
)
def get_advice_status(
    request: Request, authenticated: Authenticated
) -> AdviceProviderStatusResponse:
    del authenticated
    return _status_response(_service(request).provider_outcome())


@router.post(
    "/advice",
    operation_id="generateFinancialAdvice",
    response_model=AdviceResponse,
    responses=_problem_responses(401, 404, 409, 422),
)
def generate_advice(
    payload: AdviceRequest,
    request: Request,
    authenticated: Authenticated,
) -> AdviceResponse:
    service = _service(request)
    currency = Currency(payload.currency or authenticated.profile.base_currency.code)
    period = _analytics_period(
        service,
        authenticated.profile.timezone,
        payload.period_start,
        payload.period_end,
    )
    outcome = service.generate(
        owner_id=authenticated.profile.id,
        timezone=authenticated.profile.timezone,
        currency=currency,
        period=period,
        horizon=payload.through,
        scenario_id=payload.scenario_id,
        user_text=payload.question,
        allow_external_user_text=payload.allow_external_user_text,
    )
    return AdviceResponse(
        **_status_response(outcome).model_dump(),
        advice=outcome.advice,
        evidence=list(outcome.evidence),
        evidence_ids=list(outcome.evidence_ids),
        error_code=outcome.error_code,
        retry_after_seconds=outcome.retry_after_seconds,
        privacy=AdvicePrivacyResponse(
            external_user_text_shared=outcome.external_user_text_shared,
            redactions_applied=outcome.redactions_applied,
        ),
    )


def _analytics_period(
    service: AdviceService,
    timezone: str,
    period_start: date | None,
    period_end: date | None,
) -> AnalyticsPeriod:
    now = service.now()
    if period_start is None and period_end is None:
        return default_period(now, timezone, PeriodGranularity.MONTH)
    assert period_start is not None and period_end is not None
    period = AnalyticsPeriod(period_start, period_end, timezone, PeriodGranularity.MONTH)
    latest = default_period(now, timezone, PeriodGranularity.MONTH)
    if period.start > now.astimezone(ZoneInfo(timezone)).date() or period.end > latest.end:
        raise ApplicationError(
            status=422,
            code="invalid_advice_period",
            title="Invalid advice period",
            detail="The advice period cannot extend beyond the current local month.",
        )
    return period


def _status_response(outcome: AdviceOutcome) -> AdviceProviderStatusResponse:
    return AdviceProviderStatusResponse(
        status=outcome.status.value,
        provider=outcome.descriptor.provider,
        model=outcome.descriptor.model,
        endpoint_scope=outcome.descriptor.endpoint_scope,
        capabilities=ProviderCapabilitiesResponse(
            json_schema=outcome.capabilities.json_schema,
            system_messages=outcome.capabilities.system_messages,
            non_thinking=outcome.capabilities.non_thinking,
        ),
        prompt_version=outcome.prompt_version,
        context_version=outcome.context_version,
    )
