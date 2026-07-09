"""Rate-limiting middleware backed by RateLimitService."""

from starlette.requests import Request
from starlette.responses import Response

from llmops_gateway.domain.entities.auth_context import AuthenticatedPrincipal
from llmops_gateway.middleware.error_handling import to_error_response
from llmops_gateway.middleware.exempt_paths import is_exempt_path
from llmops_gateway.services.gateway_service import DEFAULT_TENANT_ID
from llmops_gateway.services.rate_limit_service import RateLimitExceededError, RateLimitService


async def rate_limit_middleware_dispatch(request: Request, call_next) -> Response:
    try:
        return await _rate_limit_middleware_impl(request, call_next)
    except RateLimitExceededError as exc:
        response = to_error_response(request, exc)
        if response is not None:
            return response
        raise


async def _rate_limit_middleware_impl(request: Request, call_next) -> Response:
    if is_exempt_path(request.url.path):
        return await call_next(request)

    tenant_id = getattr(request.state, "tenant_id", None) or DEFAULT_TENANT_ID
    principal: AuthenticatedPrincipal | None = getattr(request.state, "auth", None)
    limit_override = principal.rate_limit_per_minute if principal else None

    rate_limit_service: RateLimitService = request.app.state.rate_limit_service
    await rate_limit_service.check_and_increment(
        tenant_id,
        limit_per_minute=limit_override,
    )
    return await call_next(request)
