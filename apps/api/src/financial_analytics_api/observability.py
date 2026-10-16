from __future__ import annotations

from collections import Counter
from threading import Lock

from fastapi import APIRouter, Request, Response

from financial_analytics_infra.database import JobQueueSnapshot

router = APIRouter(tags=["operations"])


class MetricsRegistry:
    """In-process registry with an intentionally bounded label set."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._requests: Counter[tuple[str, str]] = Counter()
        self._duration_count = 0
        self._duration_sum = 0.0

    def observe_request(self, method: str, status: int, duration_seconds: float) -> None:
        status_class = f"{status // 100}xx"
        allowed_methods = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
        safe_method = method if method in allowed_methods else "OTHER"
        with self._lock:
            self._requests[(safe_method, status_class)] += 1
            self._duration_count += 1
            self._duration_sum += duration_seconds

    def render(
        self,
        *,
        ready: bool,
        jobs: JobQueueSnapshot,
        provider_status: str,
    ) -> str:
        with self._lock:
            requests = tuple(sorted(self._requests.items()))
            duration_count = self._duration_count
            duration_sum = self._duration_sum
        lines = [
            "# HELP financial_analytics_http_requests_total "
            "HTTP requests by method and status class.",
            "# TYPE financial_analytics_http_requests_total counter",
        ]
        lines.extend(
            "financial_analytics_http_requests_total"
            f'{{method="{method}",status_class="{status}"}} {count}'
            for (method, status), count in requests
        )
        lines.extend(
            [
                "# HELP financial_analytics_http_request_duration_seconds "
                "Request duration without route labels.",
                "# TYPE financial_analytics_http_request_duration_seconds summary",
                f"financial_analytics_http_request_duration_seconds_count {duration_count}",
                f"financial_analytics_http_request_duration_seconds_sum {duration_sum:.9f}",
                "# HELP financial_analytics_ready Whether mandatory API dependencies are ready.",
                "# TYPE financial_analytics_ready gauge",
                f"financial_analytics_ready {int(ready)}",
                "# HELP financial_analytics_jobs Jobs by non-sensitive queue state.",
                "# TYPE financial_analytics_jobs gauge",
                f'financial_analytics_jobs{{state="pending"}} {jobs.pending}',
                f'financial_analytics_jobs{{state="leased"}} {jobs.leased}',
                f'financial_analytics_jobs{{state="dead_letter"}} {jobs.dead_letter}',
                "# HELP financial_analytics_provider_status Optional advice provider state.",
                "# TYPE financial_analytics_provider_status gauge",
                f'financial_analytics_provider_status{{status="{provider_status}"}} 1',
                "",
            ]
        )
        return "\n".join(lines)


@router.get("/metrics", response_class=Response, include_in_schema=False)
async def metrics(request: Request) -> Response:
    database_ready = await request.app.state.readiness_check()
    jobs_ready = await request.app.state.job_readiness_check()
    ready = database_ready and jobs_ready
    snapshot = request.app.state.job_snapshot() if jobs_ready else JobQueueSnapshot(0, 0, 0)
    provider_status = request.app.state.advice_service.provider_outcome().status.value
    body = request.app.state.metrics.render(
        ready=ready,
        jobs=snapshot,
        provider_status=provider_status,
    )
    return Response(body, media_type="text/plain; version=0.0.4; charset=utf-8")
