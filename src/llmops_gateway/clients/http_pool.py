"""Shared, connection-pooled httpx.AsyncClient factory for outbound provider calls.

Every LLMProvider adapter gets its own client (distinct base_url/auth
headers) built through this factory, so keep-alive connection pooling and
sizing limits stay consistent across providers and RoutingService never pays
TCP/TLS handshake cost on every request under load.
"""

import httpx

DEFAULT_LIMITS = httpx.Limits(max_connections=200, max_keepalive_connections=50)


def create_http_client(
    base_url: str,
    *,
    timeout_seconds: float = 60.0,
    headers: dict[str, str] | None = None,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=base_url,
        timeout=timeout_seconds,
        headers=headers,
        limits=DEFAULT_LIMITS,
    )
