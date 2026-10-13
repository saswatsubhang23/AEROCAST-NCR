"""One error envelope for every failure: {"error": {"code", "message", "request_id", "details"?}}."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app.errors")

_CODES = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed",
          502: "upstream_error", 503: "service_unavailable"}


def _envelope(request: Request, status: int, code: str, message: str, details=None) -> JSONResponse:
    error = {
        "code": code,
        "message": message,
        "request_id": getattr(request.state, "request_id", None),
    }
    if details is not None:
        error["details"] = details
    return JSONResponse(status_code=status, content={"error": error})


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        # Routes may pass {"code": ..., "message": ...} as the detail to give clients a stable, machine-readable code.
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            return _envelope(request, exc.status_code, exc.detail["code"], str(exc.detail.get("message", "")), exc.detail.get("details"))
        code = _CODES.get(exc.status_code, "http_error")
        return _envelope(request, exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()
        ]
        return _envelope(request, 422, "validation_error", "Request validation failed.", details)

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception):
        # Full traceback goes to the log; the client only gets the request id.
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return _envelope(request, 500, "internal_error", "An unexpected error occurred.")
