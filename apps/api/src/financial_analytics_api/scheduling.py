from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Query, Request, status
from pydantic import Field, field_validator, model_validator

from financial_analytics_api.identity import Authenticated
from financial_analytics_api.ledger import (
    ApiModel,
    MoneyInput,
    MoneyResponse,
    MutatingSession,
    _problem_responses,
    _request_id,
)
from financial_analytics_app import SchedulingService
from financial_analytics_domain import (
    CatchUpPolicy,
    Instant,
    MissingDayPolicy,
    OutboxJob,
    RecurrenceFrequency,
    RecurringOperation,
    RecurringRule,
    TransactionKind,
)

router = APIRouter(prefix="/api/v1")


class RecurringOperationInput(ApiModel):
    kind: TransactionKind
    account_id: UUID
    destination_account_id: UUID | None = None
    category_id: UUID | None = None
    money: MoneyInput
    description: str = Field(default="", max_length=1000)
    tag_ids: list[UUID] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_shape(self) -> RecurringOperationInput:
        if Decimal(self.money.amount) <= 0:
            raise ValueError("recurring amount must be positive")
        if self.kind in {TransactionKind.INCOME, TransactionKind.EXPENSE}:
            if self.category_id is None or self.destination_account_id is not None:
                raise ValueError("income and expense require category_id only")
        elif self.kind is TransactionKind.TRANSFER:
            if self.category_id is not None or self.destination_account_id is None:
                raise ValueError("transfer requires destination_account_id only")
        else:
            raise ValueError("recurring operation must be income, expense, or transfer")
        return self

    def to_domain(self) -> RecurringOperation:
        return RecurringOperation(
            kind=self.kind,
            account_id=self.account_id,
            destination_account_id=self.destination_account_id,
            category_id=self.category_id,
            amount=self.money.to_domain(),
            description=self.description,
            tag_ids=tuple(self.tag_ids),
        )


class RecurringScheduleInput(ApiModel):
    frequency: RecurrenceFrequency
    starts_on: date
    local_time: time
    timezone: str = Field(min_length=1, max_length=100)
    missing_day_policy: MissingDayPolicy = MissingDayPolicy.LAST_DAY
    catch_up_policy: CatchUpPolicy = CatchUpPolicy.ALL
    end_date: date | None = None

    @field_validator("local_time")
    @classmethod
    def reject_time_offset(cls, value: time) -> time:
        if value.tzinfo is not None:
            raise ValueError("local_time must not include a UTC offset")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("timezone must be an IANA timezone") from error
        return value

    @model_validator(mode="after")
    def validate_end_date(self) -> RecurringScheduleInput:
        if self.end_date is not None and self.end_date < self.starts_on:
            raise ValueError("end_date must not be earlier than starts_on")
        return self


class CreateRecurringRuleRequest(RecurringScheduleInput):
    operation: RecurringOperationInput


class UpdateRecurringRuleRequest(CreateRecurringRuleRequest):
    version: int = Field(ge=1)


class RuleVersionRequest(ApiModel):
    version: int = Field(ge=1)


class PreviewOccurrencesRequest(RecurringScheduleInput):
    from_at: datetime | None = None
    count: int = Field(default=10, ge=1, le=100)

    @field_validator("from_at")
    @classmethod
    def require_aware_from_at(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("from_at must include a UTC offset")
        return value


class RecurringOperationResponse(ApiModel):
    kind: TransactionKind
    account_id: UUID
    destination_account_id: UUID | None
    category_id: UUID | None
    money: MoneyResponse
    description: str
    tag_ids: list[UUID]


class RecurringRuleResponse(ApiModel):
    id: UUID
    operation: RecurringOperationResponse
    frequency: RecurrenceFrequency
    starts_on: date
    local_time: time
    timezone: str
    missing_day_policy: MissingDayPolicy
    catch_up_policy: CatchUpPolicy
    end_date: date | None
    next_occurrence_at: datetime | None
    status: str
    version: int


class PreviewOccurrenceResponse(ApiModel):
    occurrence_at: datetime
    local_at: datetime


class DeadLetterJobResponse(ApiModel):
    id: UUID
    rule_id: UUID
    occurrence_at: datetime
    state: str
    attempts: int
    max_attempts: int
    last_error: str | None


def _service(request: Request) -> SchedulingService:
    return request.app.state.scheduling_service  # type: ignore[no-any-return]


@router.post(
    "/recurring-rules/preview",
    tags=["recurring-rules"],
    operation_id="previewRecurringOccurrences",
    response_model=list[PreviewOccurrenceResponse],
    responses=_problem_responses(401, 422),
)
def preview_occurrences(
    payload: PreviewOccurrencesRequest,
    request: Request,
    authenticated: Authenticated,
) -> list[PreviewOccurrenceResponse]:
    del authenticated
    occurrences = _service(request).preview(
        frequency=payload.frequency,
        starts_on=payload.starts_on,
        local_time=payload.local_time,
        timezone=payload.timezone,
        missing_day_policy=payload.missing_day_policy,
        end_date=payload.end_date,
        from_at=None if payload.from_at is None else Instant(payload.from_at),
        limit=payload.count,
    )
    zone = ZoneInfo(payload.timezone)
    return [
        PreviewOccurrenceResponse(
            occurrence_at=value.value,
            local_at=value.value.astimezone(zone),
        )
        for value in occurrences
    ]


@router.post(
    "/recurring-rules",
    tags=["recurring-rules"],
    operation_id="createRecurringRule",
    response_model=RecurringRuleResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_problem_responses(401, 403, 404, 409, 422),
)
def create_rule(
    payload: CreateRecurringRuleRequest,
    request: Request,
    authenticated: MutatingSession,
) -> RecurringRuleResponse:
    rule = _service(request).create_rule(
        owner_id=authenticated.profile.id,
        actor_id=authenticated.profile.id,
        operation=payload.operation.to_domain(),
        frequency=payload.frequency,
        starts_on=payload.starts_on,
        local_time=payload.local_time,
        timezone=payload.timezone,
        missing_day_policy=payload.missing_day_policy,
        catch_up_policy=payload.catch_up_policy,
        end_date=payload.end_date,
        request_id=_request_id(request),
    )
    return _rule_response(rule)


@router.get(
    "/recurring-rules",
    tags=["recurring-rules"],
    operation_id="listRecurringRules",
    response_model=list[RecurringRuleResponse],
    responses=_problem_responses(401),
)
def list_rules(request: Request, authenticated: Authenticated) -> list[RecurringRuleResponse]:
    return [_rule_response(rule) for rule in _service(request).list_rules(authenticated.profile.id)]


@router.get(
    "/recurring-rules/{rule_id}",
    tags=["recurring-rules"],
    operation_id="getRecurringRule",
    response_model=RecurringRuleResponse,
    responses=_problem_responses(401, 404),
)
def get_rule(
    rule_id: UUID, request: Request, authenticated: Authenticated
) -> RecurringRuleResponse:
    return _rule_response(_service(request).get_rule(authenticated.profile.id, rule_id))


@router.put(
    "/recurring-rules/{rule_id}",
    tags=["recurring-rules"],
    operation_id="updateRecurringRule",
    response_model=RecurringRuleResponse,
    responses=_problem_responses(401, 403, 404, 409, 422),
)
def update_rule(
    rule_id: UUID,
    payload: UpdateRecurringRuleRequest,
    request: Request,
    authenticated: MutatingSession,
) -> RecurringRuleResponse:
    rule = _service(request).update_rule(
        owner_id=authenticated.profile.id,
        actor_id=authenticated.profile.id,
        rule_id=rule_id,
        expected_version=payload.version,
        operation=payload.operation.to_domain(),
        frequency=payload.frequency,
        starts_on=payload.starts_on,
        local_time=payload.local_time,
        timezone=payload.timezone,
        missing_day_policy=payload.missing_day_policy,
        catch_up_policy=payload.catch_up_policy,
        end_date=payload.end_date,
        request_id=_request_id(request),
    )
    return _rule_response(rule)


@router.post(
    "/recurring-rules/{rule_id}/pause",
    tags=["recurring-rules"],
    operation_id="pauseRecurringRule",
    response_model=RecurringRuleResponse,
    responses=_problem_responses(401, 403, 404, 409),
)
def pause_rule(
    rule_id: UUID,
    payload: RuleVersionRequest,
    request: Request,
    authenticated: MutatingSession,
) -> RecurringRuleResponse:
    return _rule_response(
        _service(request).pause_rule(
            authenticated.profile.id,
            authenticated.profile.id,
            rule_id,
            payload.version,
            _request_id(request),
        )
    )


@router.post(
    "/recurring-rules/{rule_id}/resume",
    tags=["recurring-rules"],
    operation_id="resumeRecurringRule",
    response_model=RecurringRuleResponse,
    responses=_problem_responses(401, 403, 404, 409),
)
def resume_rule(
    rule_id: UUID,
    payload: RuleVersionRequest,
    request: Request,
    authenticated: MutatingSession,
) -> RecurringRuleResponse:
    return _rule_response(
        _service(request).resume_rule(
            authenticated.profile.id,
            authenticated.profile.id,
            rule_id,
            payload.version,
            _request_id(request),
        )
    )


@router.get(
    "/recurring-jobs/dead-letter",
    tags=["recurring-jobs"],
    operation_id="listDeadLetterJobs",
    response_model=list[DeadLetterJobResponse],
    responses=_problem_responses(401),
)
def list_dead_letters(
    request: Request,
    authenticated: Authenticated,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[DeadLetterJobResponse]:
    jobs = _service(request).list_dead_letters(authenticated.profile.id)
    return [_dead_letter_response(job) for job in jobs[:limit]]


@router.post(
    "/recurring-jobs/{job_id}/retry",
    tags=["recurring-jobs"],
    operation_id="retryDeadLetterJob",
    response_model=DeadLetterJobResponse,
    responses=_problem_responses(401, 403, 404, 409),
)
def retry_dead_letter(
    job_id: UUID,
    request: Request,
    authenticated: MutatingSession,
) -> DeadLetterJobResponse:
    job = _service(request).retry_dead_letter(
        owner_id=authenticated.profile.id,
        actor_id=authenticated.profile.id,
        job_id=job_id,
        request_id=_request_id(request),
    )
    return _dead_letter_response(job)


def _rule_response(rule: RecurringRule) -> RecurringRuleResponse:
    operation = rule.operation
    return RecurringRuleResponse(
        id=rule.id,
        operation=RecurringOperationResponse(
            kind=operation.kind,
            account_id=operation.account_id,
            destination_account_id=operation.destination_account_id,
            category_id=operation.category_id,
            money=MoneyResponse(
                amount=f"{operation.amount.amount:.{operation.amount.currency.minor_units}f}",
                currency=operation.amount.currency.code,
            ),
            description=operation.description,
            tag_ids=list(operation.tag_ids),
        ),
        frequency=rule.frequency,
        starts_on=rule.starts_on,
        local_time=rule.local_time,
        timezone=rule.timezone,
        missing_day_policy=rule.missing_day_policy,
        catch_up_policy=rule.catch_up_policy,
        end_date=rule.end_date,
        next_occurrence_at=(
            None
            if rule.next_occurrence_at is None
            else rule.next_occurrence_at.value.astimezone(UTC)
        ),
        status=rule.status.value,
        version=rule.version,
    )


def _dead_letter_response(job: OutboxJob) -> DeadLetterJobResponse:
    return DeadLetterJobResponse(
        id=job.id,
        rule_id=job.rule_id,
        occurrence_at=job.occurrence_at.value,
        state=job.state.value,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        last_error=job.last_error,
    )
