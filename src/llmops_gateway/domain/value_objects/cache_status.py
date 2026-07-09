from enum import StrEnum


class CacheStatus(StrEnum):
    """Outcome of the dual-layer cache lookup for a single request.

    Surfaced to clients via the `X-Cache-Status` response header and persisted
    on `requests.cache_status` for cost/latency analytics.
    """

    MISS = "MISS"
    EXACT_HIT = "EXACT_HIT"
    SEMANTIC_HIT = "SEMANTIC_HIT"
    BYPASSED = "BYPASSED"  # caller opted out, or a circuit breaker skipped the cache layer
