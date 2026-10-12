from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ProblemDetails(BaseModel):
    type: str
    title: str
    status: int
    detail: str
    code: str
    instance: str
    request_id: str
    correlation_id: str
    errors: list[dict[str, Any]] | None = None


class ApplicationError(Exception):
    def __init__(self, *, status: int, code: str, title: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail


class DependencyUnavailableError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            status=503,
            code="dependency_unavailable",
            title="Service unavailable",
            detail="A required service dependency is unavailable.",
        )


def _problem_response(
    request: Request,
    *,
    status: int,
    code: str,
    title: str,
    detail: str,
    errors: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unavailable")
    correlation_id = getattr(request.state, "correlation_id", request_id)
    problem = ProblemDetails(
        type=f"urn:financial-analytics:error:{code}",
        title=title,
        status=status,
        detail=detail,
        code=code,
        instance=request.url.path,
        request_id=request_id,
        correlation_id=correlation_id,
        errors=errors,
    )
    return JSONResponse(
        status_code=status,
        content=problem.model_dump(exclude_none=True),
        media_type="application/problem+json",
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApplicationError)
    async def application_error_handler(request: Request, exc: ApplicationError) -> JSONResponse:
        return _problem_response(
            request,
            status=exc.status,
            code=exc.code,
            title=exc.title,
            detail=exc.detail,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [
            {
                "location": [str(part) for part in error["loc"]],
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        return _problem_response(
            request,
            status=422,
            code="validation_error",
            title="Validation failed",
            detail="The request did not satisfy the API contract.",
            errors=errors,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        title = "Not found" if exc.status_code == 404 else "HTTP error"
        code = "not_found" if exc.status_code == 404 else "http_error"
        return _problem_response(
            request,
            status=exc.status_code,
            code=code,
            title=title,
            detail=str(exc.detail),
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled request error: %s", type(exc).__name__)
        return _problem_response(
            request,
            status=500,
            code="internal_error",
            title="Internal server error",
            detail="The server could not complete the request.",
        )
