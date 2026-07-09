"""Dependency health probes for liveness/readiness endpoints."""

import asyncio
from dataclasses import dataclass

import structlog
from qdrant_client import AsyncQdrantClient
from redis.asyncio import Redis
from sqlalchemy import text

from llmops_gateway.persistence.database import Database

logger = structlog.get_logger(__name__)

_PROBE_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class DependencyStatus:
    name: str
    status: str
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    status: str
    dependencies: list[DependencyStatus]

    @property
    def is_ready(self) -> bool:
        return self.status == "ok"


class HealthService:
    def __init__(
        self,
        database: Database,
        redis: Redis,
        qdrant: AsyncQdrantClient,
    ) -> None:
        self._database = database
        self._redis = redis
        self._qdrant = qdrant

    async def check_readiness(self) -> ReadinessReport:
        results = await asyncio.gather(
            self._check_postgres(),
            self._check_redis(),
            self._check_qdrant(),
            return_exceptions=True,
        )
        dependencies: list[DependencyStatus] = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning("readiness_probe_failed", error=str(result))
                dependencies.append(
                    DependencyStatus(name="unknown", status="error", detail=str(result))
                )
            else:
                dependencies.append(result)

        overall = "ok" if all(dep.status == "ok" for dep in dependencies) else "degraded"
        return ReadinessReport(status=overall, dependencies=dependencies)

    async def _check_postgres(self) -> DependencyStatus:
        try:
            async with asyncio.timeout(_PROBE_TIMEOUT_SECONDS):
                async with self._database.session() as session:
                    await session.execute(text("SELECT 1"))
            return DependencyStatus(name="postgres", status="ok")
        except Exception as exc:  # noqa: BLE001
            return DependencyStatus(name="postgres", status="error", detail=str(exc))

    async def _check_redis(self) -> DependencyStatus:
        try:
            async with asyncio.timeout(_PROBE_TIMEOUT_SECONDS):
                pong = await self._redis.ping()
            if pong:
                return DependencyStatus(name="redis", status="ok")
            return DependencyStatus(name="redis", status="error", detail="PING returned falsy")
        except Exception as exc:  # noqa: BLE001
            return DependencyStatus(name="redis", status="error", detail=str(exc))

    async def _check_qdrant(self) -> DependencyStatus:
        try:
            async with asyncio.timeout(_PROBE_TIMEOUT_SECONDS):
                await self._qdrant.get_collections()
            return DependencyStatus(name="qdrant", status="ok")
        except Exception as exc:  # noqa: BLE001
            return DependencyStatus(name="qdrant", status="error", detail=str(exc))
