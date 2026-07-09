"""Scheduled job: purge expired semantic-cache metadata (stub for future GC)."""

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


async def gc_expired_cache_entries(ctx: dict[str, Any]) -> None:
    """Placeholder — Qdrant TTL eviction and cache_entries_meta cleanup TBD."""
    logger.info("gc_expired_cache_entries_noop")
