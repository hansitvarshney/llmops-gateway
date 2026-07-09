"""API-key authentication middleware.

Validates the configured API-key header against hashed keys in Postgres
(cached in Redis) and attaches the resolved tenant/principal to
`request.state` for downstream handlers and rate limiting.
"""

from starlette.requests import Request
from starlette.responses import Response

from llmops_gateway.config.settings import get_settings
from llmops_gateway.domain.entities.auth_context import AuthenticatedPrincipal
from llmops_gateway.domain.exceptions.auth_errors import (
    AuthenticationError,
    AuthorizationError,
    InsufficientScopeError,
)
from llmops_gateway.middleware.error_handling import to_error_response
from llmops_gateway.middleware.exempt_paths import is_exempt_path
from llmops_gateway.middleware.scopes import (
    principal_has_any_scope,
    required_scopes_for_request,
)
from llmops_gateway.services.auth_service import AuthService
from llmops_gateway.services.gateway_service import DEFAULT_TENANT_ID


async def auth_middleware_dispatch(request: Request, call_next) -> Response:
    try:
        return await _auth_middleware_impl(request, call_next)
    except (AuthenticationError, AuthorizationError, InsufficientScopeError) as exc:
        response = to_error_response(request, exc)
        if response is not None:
            return response
        raise


async def _auth_middleware_impl(request: Request, call_next) -> Response:
    if is_exempt_path(request.url.path):
        return await call_next(request)

    settings = get_settings()
    if not settings.auth_require_api_key:
        _attach_anonymous_principal(request)
        return await call_next(request)

    header_name = settings.api_key_header_name
    raw_key = request.headers.get(header_name)
    if not raw_key:
        raise AuthenticationError(f"Missing {header_name} header")

    auth_service: AuthService = request.app.state.auth_service
    principal = await auth_service.authenticate(raw_key)
    if principal is None:
        raise AuthenticationError("Invalid API key")

    if principal.tenant_status != "active":
        raise AuthorizationError("Tenant is not active")

    required = required_scopes_for_request(request.url.path, request.method)
    if required is not None and not principal_has_any_scope(principal.scopes, required):
        raise InsufficientScopeError(next(iter(required)))

    _attach_principal(request, principal)
    return await call_next(request)


def _attach_principal(request: Request, principal: AuthenticatedPrincipal) -> None:
    request.state.auth = principal
    request.state.tenant_id = principal.tenant_id
    request.state.api_key_id = principal.api_key_id
    request.state.scopes = principal.scopes


def _attach_anonymous_principal(request: Request) -> None:
    principal = AuthenticatedPrincipal(
        tenant_id=DEFAULT_TENANT_ID,
        api_key_id="",
        tenant_status="active",
        scopes=frozenset({"*"}),
    )
    request.state.auth = principal
    request.state.tenant_id = principal.tenant_id
    request.state.api_key_id = None
    request.state.scopes = principal.scopes
