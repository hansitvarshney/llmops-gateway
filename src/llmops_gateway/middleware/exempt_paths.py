"""Paths that bypass auth and rate limiting."""

EXEMPT_PATHS = frozenset(
    {
        "/health",
        "/health/ready",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/metrics",
    }
)


def is_exempt_path(path: str) -> bool:
    return path in EXEMPT_PATHS or path.startswith("/metrics/")
