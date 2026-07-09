"""FastAPI application factory.

Wires together every infra client and service exactly once at startup
(connection pools for Postgres/Redis/Qdrant/httpx), stores them on
`app.state`, and tears them down cleanly on shutdown — no per-request
connection setup anywhere in the codebase.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_client import make_asgi_app

from llmops_gateway.api.v1.router import api_router
from llmops_gateway.caching.qdrant_semantic_cache import QdrantSemanticCache
from llmops_gateway.caching.redis_exact_cache import RedisExactCache
from llmops_gateway.clients.qdrant_client import create_qdrant_client
from llmops_gateway.clients.redis_client import create_redis_client
from llmops_gateway.config.logging import configure_logging, get_logger
from llmops_gateway.config.settings import get_settings
from llmops_gateway.config.validation import validate_settings
from llmops_gateway.embeddings.factory import build_embedding_provider
from llmops_gateway.middleware.auth import auth_middleware_dispatch
from llmops_gateway.middleware.error_handling import register_exception_handlers
from llmops_gateway.middleware.rate_limit import rate_limit_middleware_dispatch
from llmops_gateway.middleware.request_context import request_context_middleware_dispatch
from llmops_gateway.observability.exporter_factory import build_trace_exporters
from llmops_gateway.observability.otel_setup import (
    configure_otel,
    instrument_fastapi,
    shutdown_otel,
)
from llmops_gateway.persistence.database import Database
from llmops_gateway.providers.registry import ProviderRegistry
from llmops_gateway.services.auth_service import AuthService
from llmops_gateway.services.background_job_service import BackgroundJobService
from llmops_gateway.services.cache_service import CacheService
from llmops_gateway.services.cost_service import CostService
from llmops_gateway.services.gateway_service import GatewayService
from llmops_gateway.services.health_service import HealthService
from llmops_gateway.services.rate_limit_service import RateLimitService
from llmops_gateway.services.routing_service import RoutingService

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    validate_settings(settings)
    configure_logging(settings)
    logger.info("starting_up", environment=settings.environment.value)

    configure_otel(settings)
    if settings.tracing_enabled:
        instrument_fastapi(app)

    app.state.db = Database(settings)
    app.state.redis = create_redis_client(settings)
    app.state.qdrant = create_qdrant_client(settings)
    app.state.provider_registry = ProviderRegistry(settings)

    embedding_provider = build_embedding_provider(settings)
    app.state.embedding_provider = embedding_provider
    # Eagerly load the (potentially multi-second) local model now, so the
    # first real request never pays that cold-start cost.
    await embedding_provider.warm_up()

    exact_cache = RedisExactCache(app.state.redis, settings.redis_exact_cache_ttl_seconds)
    semantic_cache = QdrantSemanticCache(
        app.state.qdrant,
        embedding_provider,
        settings.semantic_cache_similarity_threshold,
        settings.qdrant_search_timeout_ms,
    )
    await semantic_cache.ensure_collection()

    cache_service = CacheService(
        exact_cache,
        semantic_cache,
        app.state.redis,
        coalescing_lock_ttl_seconds=settings.cache_coalescing_lock_ttl_seconds,
        coalescing_wait_seconds=settings.cache_coalescing_wait_seconds,
        coalescing_poll_interval_seconds=settings.cache_coalescing_poll_interval_seconds,
    )
    routing_service = RoutingService(app.state.provider_registry, settings)
    cost_service = CostService(
        app.state.db,
        app.state.redis,
        pricing_cache_ttl_seconds=settings.cost_pricing_cache_ttl_seconds,
    )
    app.state.auth_service = AuthService(
        app.state.db,
        app.state.redis,
        pepper=settings.auth_api_key_pepper,
        cache_ttl_seconds=settings.auth_cache_ttl_seconds,
    )
    app.state.rate_limit_service = RateLimitService(
        app.state.redis,
        default_limit_per_minute=settings.default_rate_limit_per_minute,
        enabled=settings.rate_limit_enabled,
        fail_open=settings.rate_limit_fail_open,
    )
    app.state.health_service = HealthService(
        app.state.db,
        app.state.redis,
        app.state.qdrant,
    )
    background_jobs = BackgroundJobService(settings)
    await background_jobs.connect()
    app.state.background_jobs = background_jobs
    trace_exporters = build_trace_exporters(settings)

    app.state.gateway_service = GatewayService(
        cache_service,
        routing_service,
        cost_service,
        database=app.state.db,
        trace_exporters=trace_exporters,
        background_jobs=background_jobs,
    )

    logger.info(
        "startup_complete",
        embedding_provider=embedding_provider.model_id,
        trace_exporters=[type(e).__name__ for e in trace_exporters],
    )
    try:
        yield
    finally:
        logger.info("shutting_down")
        await app.state.provider_registry.aclose_all()
        await app.state.background_jobs.close()
        await app.state.db.dispose()
        await app.state.redis.aclose()
        await app.state.qdrant.close()
        shutdown_otel()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="LLMOps Gateway",
        description="Async multi-provider LLM gateway with dual-layer semantic caching, "
        "cost tracking, and tracing.",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Order matters: Starlette runs middleware in reverse registration order for
    # the request phase, so RequestContext (trace_id) must be added last to run first.
    @app.middleware("http")
    async def rate_limit_http_middleware(request, call_next):
        return await rate_limit_middleware_dispatch(request, call_next)

    @app.middleware("http")
    async def auth_http_middleware(request, call_next):
        return await auth_middleware_dispatch(request, call_next)

    @app.middleware("http")
    async def request_context_http_middleware(request, call_next):
        return await request_context_middleware_dispatch(request, call_next)

    register_exception_handlers(app)

    app.include_router(api_router)
    if settings.metrics_enabled:
        app.mount("/metrics", make_asgi_app())

    return app


app = create_app()
