"""Centralized exception -> HTTP response translation.

Ensures internal exception types never leak stack traces to clients, and
that every error response still carries the X-Trace-Id for support/debugging.
"""

import math

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from llmops_gateway.domain.exceptions.auth_errors import (
    AuthenticationError,
    AuthorizationError,
    InsufficientScopeError,
)
from llmops_gateway.providers.base import ProviderError
from llmops_gateway.services.rate_limit_service import RateLimitExceededError
from llmops_gateway.services.routing_service import AllProvidersExhaustedError

logger = structlog.get_logger(__name__)


def _trace_id(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


def _error_response(
    request: Request,
    *,
    status_code: int,
    error: str,
    message: str | None = None,
    headers: dict[str, str] | None = None,
    **extra: object,
) -> JSONResponse:
    content: dict[str, object] = {"error": error, "trace_id": _trace_id(request)}
    if message is not None:
        content["message"] = message
    content.update(extra)
    return JSONResponse(status_code=status_code, content=content, headers=headers or {})


def to_error_response(request: Request, exc: Exception) -> JSONResponse | None:
    """Map domain/security exceptions to JSON responses.

    Used by HTTP middleware (which FastAPI does not route through
    `@app.exception_handler`) and by the registered handlers below.
    """
    if isinstance(exc, AuthenticationError):
        return _error_response(
            request, status_code=401, error="unauthorized", message=exc.message
        )
    if isinstance(exc, InsufficientScopeError):
        return _error_response(
            request,
            status_code=403,
            error="forbidden",
            message=exc.message,
            required_scope=exc.required_scope,
        )
    if isinstance(exc, AuthorizationError):
        return _error_response(request, status_code=403, error="forbidden", message=exc.message)
    if isinstance(exc, RateLimitExceededError):
        retry_after = max(1, math.ceil(exc.retry_after_seconds))
        return _error_response(
            request,
            status_code=429,
            error="rate_limit_exceeded",
            message="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
            retry_after_seconds=retry_after,
        )
    return None


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AuthenticationError)
    async def authentication_error_handler(
        request: Request, exc: AuthenticationError
    ) -> JSONResponse:
        return to_error_response(request, exc)  # type: ignore[return-value]

    @app.exception_handler(InsufficientScopeError)
    async def insufficient_scope_handler(
        request: Request, exc: InsufficientScopeError
    ) -> JSONResponse:
        return to_error_response(request, exc)  # type: ignore[return-value]

    @app.exception_handler(AuthorizationError)
    async def authorization_error_handler(
        request: Request, exc: AuthorizationError
    ) -> JSONResponse:
        return to_error_response(request, exc)  # type: ignore[return-value]

    @app.exception_handler(RateLimitExceededError)
    async def rate_limit_error_handler(
        request: Request, exc: RateLimitExceededError
    ) -> JSONResponse:
        return to_error_response(request, exc)  # type: ignore[return-value]

    @app.exception_handler(ProviderError)
    async def provider_error_handler(request: Request, exc: ProviderError) -> JSONResponse:
        logger.warning("provider_error", trace_id=_trace_id(request), error=str(exc))
        return _error_response(
            request,
            status_code=502,
            error="upstream_provider_error",
            message="Upstream provider request failed",
        )

    @app.exception_handler(AllProvidersExhaustedError)
    async def all_providers_exhausted_handler(
        request: Request, exc: AllProvidersExhaustedError
    ) -> JSONResponse:
        logger.warning("all_providers_exhausted", trace_id=_trace_id(request), error=str(exc))
        return _error_response(
            request,
            status_code=503,
            error="service_unavailable",
            message="All upstream providers are unavailable",
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        trace_id = _trace_id(request)
        logger.exception("unhandled_exception", trace_id=trace_id)
        return _error_response(
            request,
            status_code=500,
            error="internal_server_error",
            message="An unexpected error occurred",
        )
