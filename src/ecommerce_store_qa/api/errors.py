from dataclasses import dataclass
from http import HTTPStatus
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pymongo.errors import ConnectionFailure
from starlette.exceptions import HTTPException

from ecommerce_store_qa.application.session_service import (
    ExchangeConflictError,
    ExchangeNotFoundError,
    ExchangeTooLargeError,
    SessionNotFoundError,
)

PROBLEM_MEDIA_TYPE = "application/problem+json"


class ValidationEntry(BaseModel):
    message: str
    name: str
    entity: str


class ProblemDetails(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: str
    code: str
    trace_id: str = Field(alias="traceId")
    errors: list[ValidationEntry] = Field(default_factory=list[ValidationEntry])
    missing_properties: list[str] = Field(default_factory=list, alias="missingProperties")


@dataclass(frozen=True, slots=True)
class ErrorSpec:
    status: int
    code: str
    detail: str


class RequestProblem(Exception):
    def __init__(self, spec: ErrorSpec) -> None:
        self.spec = spec
        super().__init__(spec.code)


BAD_REQUEST = ErrorSpec(400, "invalid_request", "Request validation failed.")
UNAUTHORIZED = ErrorSpec(401, "unauthorized", "A valid API key is required.")
UNAVAILABLE = ErrorSpec(503, "service_unavailable", "The session store is unavailable.")
ERRORS: dict[type[Exception], ErrorSpec] = {
    SessionNotFoundError: ErrorSpec(404, "session_not_found", "Session was not found."),
    ExchangeNotFoundError: ErrorSpec(404, "exchange_not_found", "Exchange was not found."),
    ExchangeConflictError: ErrorSpec(409, "exchange_conflict", "The exchange ID already has different content."),
    ExchangeTooLargeError: ErrorSpec(413, "exchange_too_large", "The exchange exceeds the capture size limit."),
    ConnectionFailure: UNAVAILABLE,
}


def install_error_handlers(app: FastAPI) -> None:
    async def problem(request: Request, error: Exception) -> JSONResponse:
        if isinstance(error, RequestProblem):
            spec = error.spec
        elif isinstance(error, RequestValidationError):
            spec = BAD_REQUEST
        elif isinstance(error, HTTPException):
            spec = ErrorSpec(error.status_code, f"http_{error.status_code}", "The request could not be completed.")
        else:
            spec = next(
                (value for kind, value in ERRORS.items() if isinstance(error, kind)),
                ErrorSpec(500, "internal_error", "An unexpected error occurred."),
            )

        trace_id = uuid4().hex
        response = ProblemDetails(
            title=HTTPStatus(spec.status).phrase,
            status=spec.status,
            detail=spec.detail,
            instance=request.url.path,
            code=spec.code,
            traceId=trace_id,
        )
        headers = dict(error.headers or {}) if isinstance(error, HTTPException) else {}
        headers["X-Trace-Id"] = trace_id
        return JSONResponse(
            content=response.model_dump(by_alias=True),
            status_code=spec.status,
            media_type=PROBLEM_MEDIA_TYPE,
            headers=headers,
        )

    for kind in (RequestProblem, RequestValidationError, HTTPException, *ERRORS, Exception):
        app.add_exception_handler(kind, problem)


def problem_responses(*statuses: int) -> dict[int | str, dict[str, object]]:
    return {status: {"description": HTTPStatus(status).phrase, "model": ProblemDetails} for status in statuses}
