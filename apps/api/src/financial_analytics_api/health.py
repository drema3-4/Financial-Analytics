from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from financial_analytics_api.errors import DependencyUnavailableError, ProblemDetails

router = APIRouter(prefix="/health", tags=["health"])


class LivenessResponse(BaseModel):
    status: Literal["alive"] = "alive"


class ReadinessChecks(BaseModel):
    database: Literal["up"] = "up"


class ReadinessResponse(BaseModel):
    status: Literal["ready"] = "ready"
    checks: ReadinessChecks


@router.get("/live", response_model=LivenessResponse)
async def live() -> LivenessResponse:
    return LivenessResponse()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={
        503: {
            "description": "Required dependency unavailable",
            "content": {
                "application/problem+json": {
                    "schema": ProblemDetails.model_json_schema(
                        ref_template="#/components/schemas/{model}"
                    )
                }
            },
        }
    },
)
async def ready(request: Request) -> ReadinessResponse:
    if not await request.app.state.readiness_check():
        raise DependencyUnavailableError
    return ReadinessResponse(checks=ReadinessChecks())
