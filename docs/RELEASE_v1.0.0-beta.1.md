# Release Notes — v1.0.0-beta.1

**Date:** 2026-07-09  
**Tag:** `v1.0.0-beta.1`  
**Repository:** https://github.com/hansitvarshney/llmops-gateway

## Summary

First unified release of the LLMOps Gateway & Observability Platform — an async, multi-tenant LLM gateway with dual-layer semantic caching, multi-provider resilience, cost tracking, distributed tracing, security middleware, containerized infrastructure, arq background workers, and admin control plane APIs.

## Highlights

### Gateway & providers
- FastAPI async application with lifespan-managed connection pools
- OpenAI + Anthropic adapters (streaming and non-streaming)
- Per-provider circuit breakers, exponential backoff, cross-provider fallback

### Caching
- Redis exact-match cache (tenant-scoped, fail-closed)
- Qdrant semantic cache (cosine ≥ 0.95, filtered by tenant/model/params)
- Local sentence-transformers embeddings with startup warm-up
- Request coalescing on concurrent cache misses

### Observability & cost
- TracingService spans: `cache_lookup`, `upstream_call`, `cost_calculation`
- Postgres persistence: requests, spans, token_usage
- Versioned model pricing with Redis cache-aside
- OpenTelemetry OTLP export + optional Langfuse
- Prometheus metrics at `/metrics`

### Security & multi-tenancy
- Peppered SHA-256 API key hashing
- Redis-cached auth principals, scope checks
- Per-tenant Redis token-bucket rate limiting (429 + Retry-After)

### Infrastructure
- `/health` (liveness) and `/health/ready` (dependency probes)
- Docker Compose full stack with healthchecks
- Alembic migrations on gateway startup
- Production pepper guardrail

### Background processing
- arq workers: `persist_trace`, `export_otel_spans`, `backfill_cache`
- Idempotent trace persistence by `trace_id`

### Admin APIs
- Tenants, pricing, API keys (create/list/revoke)

## Requirements

- Python 3.11+
- PostgreSQL, Redis, Qdrant
- OpenAI and/or Anthropic API keys for upstream calls

## Quick start

```bash
cp .env.example .env
make install && make up
curl http://localhost:8000/health/ready
```

Dev API key: `llmops_dev_default_key` (header `X-API-Key`)

## Known limitations

- Streaming client disconnect mid-response is not traced
- `provider_health` and `cache_entries_meta` tables not yet written at runtime
- Embeddings API endpoint is stubbed

## Tests

127+ unit tests (1 integration test deselected by default)

```bash
make test
```
