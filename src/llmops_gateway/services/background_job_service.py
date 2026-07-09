"""Enqueue background jobs to arq (Redis) with in-process fallback."""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

import structlog
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from llmops_gateway.config.settings import Settings

logger = structlog.get_logger(__name__)


class BackgroundJobService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool: ArqRedis | None = None

    @property
    def use_arq(self) -> bool:
        return self._settings.use_arq_workers

    async def connect(self) -> None:
        if not self.use_arq:
            return
        self._pool = await create_pool(
            RedisSettings.from_dsn(self._settings.resolved_arq_redis_url)
        )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def run_trace_flush(
        self,
        *,
        persist_coro: Callable[[], Coroutine[Any, Any, None]],
        export_coro: Callable[[], Coroutine[Any, Any, None]],
        persist_payload: dict[str, Any],
        export_payload: dict[str, Any],
    ) -> None:
        if await self._try_enqueue("persist_trace", persist_payload):
            await self._try_enqueue("export_otel_spans", export_payload)
            return
        asyncio.create_task(_safe_run(persist_coro, "trace_persist"))  # noqa: RUF006
        asyncio.create_task(_safe_run(export_coro, "trace_export"))  # noqa: RUF006

    async def run_backfill(
        self,
        *,
        backfill_coro: Callable[[], Coroutine[Any, Any, None]],
        request_payload: dict[str, Any],
        response_payload: dict[str, Any],
        tenant_id: str,
    ) -> None:
        if await self._try_enqueue(
            "backfill_cache",
            None,
            args=(request_payload, response_payload, tenant_id),
        ):
            return
        asyncio.create_task(_safe_run(backfill_coro, "cache_backfill"))  # noqa: RUF006

    async def _try_enqueue(
        self,
        job_name: str,
        payload: dict[str, Any] | None,
        *,
        args: tuple[Any, ...] = (),
    ) -> bool:
        if not self.use_arq or self._pool is None:
            return False
        try:
            if payload is not None:
                await self._pool.enqueue_job(job_name, payload)
            else:
                await self._pool.enqueue_job(job_name, *args)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("arq_enqueue_failed", job=job_name, error=str(exc))
            return False


async def _safe_run(coro_factory: Callable[[], Coroutine[Any, Any, None]], label: str) -> None:
    try:
        await coro_factory()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"{label}_failed", error=str(exc))
