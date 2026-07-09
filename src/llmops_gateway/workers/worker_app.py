"""arq worker entrypoint — run via `arq llmops_gateway.workers.worker_app.WorkerSettings`."""

from arq.connections import RedisSettings
from arq.cron import cron

from llmops_gateway.caching.qdrant_semantic_cache import QdrantSemanticCache
from llmops_gateway.caching.redis_exact_cache import RedisExactCache
from llmops_gateway.clients.qdrant_client import create_qdrant_client
from llmops_gateway.clients.redis_client import create_redis_client
from llmops_gateway.config.settings import get_settings
from llmops_gateway.embeddings.factory import build_embedding_provider
from llmops_gateway.observability.exporter_factory import build_trace_exporters
from llmops_gateway.persistence.database import Database
from llmops_gateway.services.cache_service import CacheService
from llmops_gateway.workers.tasks.backfill_cache import backfill_cache
from llmops_gateway.workers.tasks.export_otel import export_otel_spans
from llmops_gateway.workers.tasks.gc_cache import gc_expired_cache_entries
from llmops_gateway.workers.tasks.persist_trace import persist_trace

settings = get_settings()


async def startup(ctx: dict) -> None:
    worker_settings = get_settings()
    ctx["settings"] = worker_settings
    ctx["db"] = Database(worker_settings)
    ctx["redis"] = create_redis_client(worker_settings)
    ctx["qdrant"] = create_qdrant_client(worker_settings)

    embedding_provider = build_embedding_provider(worker_settings)
    await embedding_provider.warm_up()

    exact_cache = RedisExactCache(
        ctx["redis"], worker_settings.redis_exact_cache_ttl_seconds
    )
    semantic_cache = QdrantSemanticCache(
        ctx["qdrant"],
        embedding_provider,
        worker_settings.semantic_cache_similarity_threshold,
        worker_settings.qdrant_search_timeout_ms,
    )
    await semantic_cache.ensure_collection()

    ctx["cache_service"] = CacheService(
        exact_cache,
        semantic_cache,
        ctx["redis"],
        coalescing_lock_ttl_seconds=worker_settings.cache_coalescing_lock_ttl_seconds,
        coalescing_wait_seconds=worker_settings.cache_coalescing_wait_seconds,
        coalescing_poll_interval_seconds=worker_settings.cache_coalescing_poll_interval_seconds,
    )
    ctx["trace_exporters"] = build_trace_exporters(worker_settings)


async def shutdown(ctx: dict) -> None:
    if "db" in ctx:
        await ctx["db"].dispose()
    if "redis" in ctx:
        await ctx["redis"].aclose()
    if "qdrant" in ctx:
        await ctx["qdrant"].close()


class WorkerSettings:
    functions = [persist_trace, backfill_cache, export_otel_spans, gc_expired_cache_entries]
    on_startup = startup
    on_shutdown = shutdown
    cron_jobs = [cron(gc_expired_cache_entries, hour=3, minute=0)]
    redis_settings = RedisSettings.from_dsn(settings.resolved_arq_redis_url)
    max_jobs = 50
    job_timeout = 120
