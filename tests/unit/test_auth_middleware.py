"""Auth and rate-limit middleware integration tests."""

import uuid
from unittest.mock import patch

import fakeredis.aioredis
import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from llmops_gateway.config.settings import Settings
from llmops_gateway.middleware.auth import auth_middleware_dispatch
from llmops_gateway.middleware.error_handling import register_exception_handlers
from llmops_gateway.middleware.rate_limit import rate_limit_middleware_dispatch
from llmops_gateway.middleware.request_context import request_context_middleware_dispatch
from llmops_gateway.persistence.models.api_key import ApiKeyModel
from llmops_gateway.persistence.models.tenant import TenantModel
from llmops_gateway.security.api_keys import hash_api_key
from llmops_gateway.services.auth_service import AuthService
from llmops_gateway.services.rate_limit_service import RateLimitService
from tests.conftest import _SQLiteDatabase

PEPPER = "middleware-test-pepper"
RAW_KEY = "llmops_middleware_test_key"
CHAT_SCOPE_KEY = "llmops_chat_scope_key"


@pytest.fixture
async def auth_app():
    database = _SQLiteDatabase()
    async with database.engine.begin() as conn:
        from llmops_gateway.persistence.models import Base

        await conn.run_sync(Base.metadata.create_all)

    tenant_id = uuid.uuid4()
    async with database.session() as session:
        session.add(
            TenantModel(
                id=tenant_id,
                name="Middleware Tenant",
                slug="middleware-tenant",
                status="active",
            )
        )
        session.add(
            ApiKeyModel(
                tenant_id=tenant_id,
                key_hash=hash_api_key(RAW_KEY, pepper=PEPPER),
                name="full-access",
                scopes=["*"],
            )
        )
        session.add(
            ApiKeyModel(
                tenant_id=tenant_id,
                key_hash=hash_api_key(CHAT_SCOPE_KEY, pepper=PEPPER),
                name="chat-only",
                scopes=["chat:write"],
            )
        )

    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    app = FastAPI()
    app.state.db = database
    app.state.redis = redis
    app.state.auth_service = AuthService(database, redis, pepper=PEPPER, cache_ttl_seconds=60)
    app.state.rate_limit_service = RateLimitService(
        redis, default_limit_per_minute=2, enabled=True
    )
    register_exception_handlers(app)

    @app.middleware("http")
    async def rate_limit_http_middleware(request, call_next):
        return await rate_limit_middleware_dispatch(request, call_next)

    @app.middleware("http")
    async def auth_http_middleware(request, call_next):
        return await auth_middleware_dispatch(request, call_next)

    @app.middleware("http")
    async def request_context_http_middleware(request, call_next):
        return await request_context_middleware_dispatch(request, call_next)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> dict[str, str]:
        return {"tenant_id": request.state.tenant_id}

    @app.get("/v1/admin/tenants")
    async def admin_tenants() -> list:
        return []

    transport = ASGITransport(app=app)
    test_settings = Settings(auth_require_api_key=True, auth_api_key_pepper=PEPPER)
    with patch("llmops_gateway.middleware.auth.get_settings", return_value=test_settings):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, tenant_id

    await database.dispose()
    await redis.aclose()


async def test_health_is_exempt_from_auth(auth_app) -> None:
    client, _ = auth_app
    response = await client.get("/health")
    assert response.status_code == 200


async def test_missing_api_key_returns_401(auth_app) -> None:
    client, _ = auth_app
    response = await client.post("/v1/chat/completions", json={})
    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"
    assert "trace_id" in response.json()


async def test_valid_api_key_authenticates_and_sets_tenant(auth_app) -> None:
    client, tenant_id = auth_app
    response = await client.post(
        "/v1/chat/completions",
        json={},
        headers={"X-API-Key": RAW_KEY},
    )
    assert response.status_code == 200
    assert response.json()["tenant_id"] == str(tenant_id)
    assert response.headers.get("X-Trace-Id")


async def test_insufficient_scope_returns_403(auth_app) -> None:
    client, _ = auth_app
    response = await client.get(
        "/v1/admin/tenants",
        headers={"X-API-Key": CHAT_SCOPE_KEY},
    )
    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"


async def test_rate_limit_returns_429_with_retry_after(auth_app) -> None:
    client, _ = auth_app
    headers = {"X-API-Key": RAW_KEY}
    await client.post("/v1/chat/completions", json={}, headers=headers)
    await client.post("/v1/chat/completions", json={}, headers=headers)
    response = await client.post("/v1/chat/completions", json={}, headers=headers)

    assert response.status_code == 429
    assert response.json()["error"] == "rate_limit_exceeded"
    assert response.headers.get("Retry-After")
