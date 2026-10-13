from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict

from financial_analytics_api.errors import ApplicationError, ProblemDetails
from financial_analytics_api.identity import Authenticated
from financial_analytics_app import AnalyticsService
from financial_analytics_domain import (
    ANOMALY_BASELINE_BUCKETS,
    ANOMALY_MINIMUM_BUCKETS,
    ANOMALY_POLICY_VERSION,
    AnalyticsBucket,
    AnalyticsPeriod,
    AnalyticsReport,
    AnomalyFlag,
    BreakdownItem,
    ComparisonMetric,
    CurrencyAnalytics,
    CurrencyComparison,
    Evidence,
    Money,
    MoneyMetric,
    PeriodComparison,
    PeriodGranularity,
    RatioMetric,
    default_period,
)

router = APIRouter(prefix="/api/v1")


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MoneyResponse(ApiModel):
    amount: str
    currency: str


class EvidenceResponse(ApiModel):
    transaction_ids: list[UUID]
    posting_ids: list[UUID]


class MoneyMetricResponse(ApiModel):
    value: MoneyResponse
    formula: str
    evidence: EvidenceResponse


class RatioMetricResponse(ApiModel):
    value: str | None
    formula: str
    numerator: MoneyResponse
    denominator: MoneyResponse
    evidence: EvidenceResponse


class BreakdownItemResponse(ApiModel):
    flow_type: str
    id: UUID | None
    name: str
    amount: MoneyResponse
    evidence: EvidenceResponse


class DashboardCurrencyResponse(ApiModel):
    currency: str
    income: MoneyMetricResponse
    expense: MoneyMetricResponse
    cash_flow: MoneyMetricResponse
    savings: MoneyMetricResponse
    mandatory_expense: MoneyMetricResponse
    mandatory_expense_share: RatioMetricResponse
    savings_rate: RatioMetricResponse
    opening_net_worth: MoneyMetricResponse
    closing_net_worth: MoneyMetricResponse
    net_worth_change: MoneyMetricResponse


class ReportCurrencyResponse(DashboardCurrencyResponse):
    category_breakdown: list[BreakdownItemResponse]
    group_breakdown: list[BreakdownItemResponse]


class PeriodResponse(ApiModel):
    start: date
    end: date
    timezone: str
    granularity: PeriodGranularity
    start_at: datetime
    end_at: datetime


class BucketResponse(ApiModel):
    start: date
    end: date
    is_complete: bool
    currencies: list[ReportCurrencyResponse]


class ComparisonMetricResponse(ApiModel):
    current: MoneyResponse
    previous: MoneyResponse
    delta: MoneyResponse
    change_rate: str | None


class CurrencyComparisonResponse(ApiModel):
    currency: str
    income: ComparisonMetricResponse
    expense: ComparisonMetricResponse
    cash_flow: ComparisonMetricResponse
    savings: ComparisonMetricResponse
    net_worth: ComparisonMetricResponse


class PeriodComparisonResponse(ApiModel):
    current_start: datetime
    current_end: datetime
    previous_start: datetime
    previous_end: datetime
    current_is_complete: bool
    currencies: list[CurrencyComparisonResponse]


class AnomalyFlagResponse(ApiModel):
    bucket_start: date
    bucket_end: date
    metric: str
    direction: str
    observed: MoneyResponse
    baseline: MoneyResponse
    deviation: MoneyResponse
    threshold: MoneyResponse
    rationale: str
    baseline_bucket_count: int
    evidence: EvidenceResponse


class AnomalyPolicyResponse(ApiModel):
    version: str
    baseline_buckets: int
    minimum_buckets: int
    baseline_statistic: str
    threshold_formula: str
    incomplete_buckets_evaluated: bool


class DashboardResponse(ApiModel):
    period: PeriodResponse
    data_through: datetime
    currency_mode: str
    combined_currency: str | None
    totals: list[DashboardCurrencyResponse]
    comparison: PeriodComparisonResponse
    anomaly_policy: AnomalyPolicyResponse
    anomalies: list[AnomalyFlagResponse]


class FinancialReportResponse(ApiModel):
    period: PeriodResponse
    data_through: datetime
    currency_mode: str
    combined_currency: str | None
    totals: list[ReportCurrencyResponse]
    buckets: list[BucketResponse]
    comparison: PeriodComparisonResponse
    anomaly_policy: AnomalyPolicyResponse
    anomalies: list[AnomalyFlagResponse]


def _problem_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    return {
        code: {
            "model": ProblemDetails,
            "content": {"application/problem+json": {}},
        }
        for code in status_codes
    }


def _service(request: Request) -> AnalyticsService:
    return request.app.state.analytics_service  # type: ignore[no-any-return]


@router.get(
    "/analytics/dashboard",
    tags=["analytics"],
    operation_id="getAnalyticsDashboard",
    response_model=DashboardResponse,
    responses=_problem_responses(401, 422),
)
def get_dashboard(
    request: Request,
    authenticated: Authenticated,
    period_start: Annotated[date | None, Query()] = None,
    period_end: Annotated[date | None, Query()] = None,
    granularity: Annotated[PeriodGranularity, Query()] = PeriodGranularity.MONTH,
) -> DashboardResponse:
    service = _service(request)
    period = _resolve_period(
        service,
        authenticated.profile.timezone,
        granularity,
        period_start,
        period_end,
    )
    report = service.report(authenticated.profile.id, period)
    return _dashboard_response(report)


@router.get(
    "/reports/financial",
    tags=["reports"],
    operation_id="getFinancialReport",
    response_model=FinancialReportResponse,
    responses=_problem_responses(401, 422),
)
def get_financial_report(
    request: Request,
    authenticated: Authenticated,
    period_start: Annotated[date, Query()],
    period_end: Annotated[date, Query()],
    granularity: Annotated[PeriodGranularity, Query()] = PeriodGranularity.MONTH,
) -> FinancialReportResponse:
    service = _service(request)
    period = _resolve_period(
        service,
        authenticated.profile.timezone,
        granularity,
        period_start,
        period_end,
    )
    return _report_response(service.report(authenticated.profile.id, period))


def _resolve_period(
    service: AnalyticsService,
    timezone: str,
    granularity: PeriodGranularity,
    period_start: date | None,
    period_end: date | None,
) -> AnalyticsPeriod:
    now = service.now()
    if period_start is None and period_end is None:
        return default_period(now, timezone, granularity)
    if period_start is None or period_end is None:
        raise ApplicationError(
            status=422,
            code="invalid_analytics_period",
            title="Invalid analytics period",
            detail="period_start and period_end must be supplied together.",
        )
    period = AnalyticsPeriod(period_start, period_end, timezone, granularity)
    latest = default_period(now, timezone, granularity)
    if period.start > now.astimezone(ZoneInfo(timezone)).date() or period.end > latest.end:
        raise ApplicationError(
            status=422,
            code="invalid_analytics_period",
            title="Invalid analytics period",
            detail="The requested period cannot extend beyond the current local bucket.",
        )
    return period


def _dashboard_response(report: AnalyticsReport) -> DashboardResponse:
    return DashboardResponse(
        period=_period_response(report.period),
        data_through=report.data_through,
        currency_mode=report.currency_mode.value,
        combined_currency=(
            None if report.combined_currency is None else report.combined_currency.code
        ),
        totals=[_dashboard_currency_response(item) for item in report.totals],
        comparison=_comparison_response(report.comparison),
        anomaly_policy=_anomaly_policy_response(),
        anomalies=[_anomaly_response(item) for item in report.anomalies],
    )


def _report_response(report: AnalyticsReport) -> FinancialReportResponse:
    return FinancialReportResponse(
        period=_period_response(report.period),
        data_through=report.data_through,
        currency_mode=report.currency_mode.value,
        combined_currency=(
            None if report.combined_currency is None else report.combined_currency.code
        ),
        totals=[_report_currency_response(item) for item in report.totals],
        buckets=[_bucket_response(item) for item in report.buckets],
        comparison=_comparison_response(report.comparison),
        anomaly_policy=_anomaly_policy_response(),
        anomalies=[_anomaly_response(item) for item in report.anomalies],
    )


def _period_response(period: AnalyticsPeriod) -> PeriodResponse:
    return PeriodResponse(
        start=period.start,
        end=period.end,
        timezone=period.timezone,
        granularity=period.granularity,
        start_at=period.start_at,
        end_at=period.end_at,
    )


def _dashboard_currency_response(item: CurrencyAnalytics) -> DashboardCurrencyResponse:
    return DashboardCurrencyResponse(
        currency=item.currency.code,
        income=_money_metric_response(item.income),
        expense=_money_metric_response(item.expense),
        cash_flow=_money_metric_response(item.cash_flow),
        savings=_money_metric_response(item.savings),
        mandatory_expense=_money_metric_response(item.mandatory_expense),
        mandatory_expense_share=_ratio_metric_response(item.mandatory_expense_share),
        savings_rate=_ratio_metric_response(item.savings_rate),
        opening_net_worth=_money_metric_response(item.opening_net_worth),
        closing_net_worth=_money_metric_response(item.closing_net_worth),
        net_worth_change=_money_metric_response(item.net_worth_change),
    )


def _report_currency_response(item: CurrencyAnalytics) -> ReportCurrencyResponse:
    return ReportCurrencyResponse(
        **_dashboard_currency_response(item).model_dump(),
        category_breakdown=[_breakdown_response(value) for value in item.category_breakdown],
        group_breakdown=[_breakdown_response(value) for value in item.group_breakdown],
    )


def _bucket_response(item: AnalyticsBucket) -> BucketResponse:
    return BucketResponse(
        start=item.start,
        end=item.end,
        is_complete=item.is_complete,
        currencies=[_report_currency_response(value) for value in item.currencies],
    )


def _money_metric_response(item: MoneyMetric) -> MoneyMetricResponse:
    return MoneyMetricResponse(
        value=_money_response(item.value),
        formula=item.formula,
        evidence=_evidence_response(item.evidence),
    )


def _ratio_metric_response(item: RatioMetric) -> RatioMetricResponse:
    return RatioMetricResponse(
        value=_decimal_response(item.value),
        formula=item.formula,
        numerator=_money_response(item.numerator),
        denominator=_money_response(item.denominator),
        evidence=_evidence_response(item.evidence),
    )


def _breakdown_response(item: BreakdownItem) -> BreakdownItemResponse:
    return BreakdownItemResponse(
        flow_type=item.flow_type,
        id=item.id,
        name=item.name,
        amount=_money_response(item.amount),
        evidence=_evidence_response(item.evidence),
    )


def _comparison_response(item: PeriodComparison) -> PeriodComparisonResponse:
    return PeriodComparisonResponse(
        current_start=item.current_start,
        current_end=item.current_end,
        previous_start=item.previous_start,
        previous_end=item.previous_end,
        current_is_complete=item.current_is_complete,
        currencies=[_currency_comparison_response(value) for value in item.currencies],
    )


def _currency_comparison_response(item: CurrencyComparison) -> CurrencyComparisonResponse:
    return CurrencyComparisonResponse(
        currency=item.currency.code,
        income=_comparison_metric_response(item.income),
        expense=_comparison_metric_response(item.expense),
        cash_flow=_comparison_metric_response(item.cash_flow),
        savings=_comparison_metric_response(item.savings),
        net_worth=_comparison_metric_response(item.net_worth),
    )


def _comparison_metric_response(item: ComparisonMetric) -> ComparisonMetricResponse:
    return ComparisonMetricResponse(
        current=_money_response(item.current),
        previous=_money_response(item.previous),
        delta=_money_response(item.delta),
        change_rate=_decimal_response(item.change_rate),
    )


def _anomaly_response(item: AnomalyFlag) -> AnomalyFlagResponse:
    return AnomalyFlagResponse(
        bucket_start=item.bucket_start,
        bucket_end=item.bucket_end,
        metric=item.metric,
        direction=item.direction,
        observed=_money_response(item.observed),
        baseline=_money_response(item.baseline),
        deviation=_money_response(item.deviation),
        threshold=_money_response(item.threshold),
        rationale=item.rationale,
        baseline_bucket_count=item.baseline_bucket_count,
        evidence=_evidence_response(item.evidence),
    )


def _anomaly_policy_response() -> AnomalyPolicyResponse:
    return AnomalyPolicyResponse(
        version=ANOMALY_POLICY_VERSION,
        baseline_buckets=ANOMALY_BASELINE_BUCKETS,
        minimum_buckets=ANOMALY_MINIMUM_BUCKETS,
        baseline_statistic="median with median absolute deviation",
        threshold_formula="max(0.50 * abs(median), 3 * MAD)",
        incomplete_buckets_evaluated=False,
    )


def _evidence_response(item: Evidence) -> EvidenceResponse:
    return EvidenceResponse(
        transaction_ids=list(item.transaction_ids), posting_ids=list(item.posting_ids)
    )


def _money_response(item: Money) -> MoneyResponse:
    return MoneyResponse(
        amount=f"{item.amount:.{item.currency.minor_units}f}", currency=item.currency.code
    )


def _decimal_response(item: Decimal | None) -> str | None:
    return None if item is None else format(item, "f")
