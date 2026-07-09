"""Shared FastAPI dependencies — DB sessions, service instances, and the
authenticated tenant, wired from objects stored on `app.state` during the
lifespan startup in main.py.
"""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from llmops_gateway.domain.entities.auth_context import AuthenticatedPrincipal
from llmops_gateway.domain.exceptions.auth_errors import AuthenticationError
from llmops_gateway.services.gateway_service import GatewayService


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.db.session() as session:
        yield session


def get_gateway_service(request: Request) -> GatewayService:
    return request.app.state.gateway_service


def get_current_tenant_id(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id is None:
        raise AuthenticationError("Request is not authenticated")
    return tenant_id


def get_current_api_key_id(request: Request) -> str | None:
    return getattr(request.state, "api_key_id", None)


def get_authenticated_principal(request: Request) -> AuthenticatedPrincipal:
    principal = getattr(request.state, "auth", None)
    if principal is None:
        raise AuthenticationError("Request is not authenticated")
    return principal
