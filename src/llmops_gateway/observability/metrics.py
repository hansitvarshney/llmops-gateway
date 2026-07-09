"""Prometheus metrics for the gateway's own health (latency, cache hit ratio,
cost/min, circuit-breaker state) — surfaced at /metrics and visualized via
the Grafana dashboards in infra/grafana/.
"""

from prometheus_client import Counter, Histogram

request_latency_seconds = Histogram(
    "llmops_gateway_request_latency_seconds",
    "End-to-end request latency observed by the gateway.",
    labelnames=("route", "cache_status"),
)

cache_lookups_total = Counter(
    "llmops_gateway_cache_lookups_total",
    "Cache lookups by layer and outcome.",
    labelnames=("layer", "outcome"),
)

provider_requests_total = Counter(
    "llmops_gateway_provider_requests_total",
    "Upstream provider calls by provider/model/outcome.",
    labelnames=("provider", "model", "outcome"),
)

request_cost_usd_total = Counter(
    "llmops_gateway_request_cost_usd_total",
    "Cumulative estimated spend, labeled by tenant/provider/model.",
    labelnames=("tenant_id", "provider", "model"),
)


def record_request_metrics(
    *,
    route: str,
    tenant_id: str,
    provider: str,
    model: str,
    cache_status: str,
    latency_ms: float,
    cost_usd: float,
) -> None:
    """Single call-site for GatewayService so every response path (cache
    hit, cache miss, streamed or not) reports the same set of metrics
    consistently. Cheap, synchronous, in-process — no I/O, so calling this
    directly on the request path adds no meaningful latency."""
    request_latency_seconds.labels(route=route, cache_status=cache_status).observe(
        latency_ms / 1000
    )
    cache_lookups_total.labels(layer="combined", outcome=cache_status).inc()
    provider_requests_total.labels(provider=provider, model=model, outcome="success").inc()
    if cost_usd:
        request_cost_usd_total.labels(tenant_id=tenant_id, provider=provider, model=model).inc(
            cost_usd
        )
