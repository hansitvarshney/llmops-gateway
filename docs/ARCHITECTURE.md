# LLMOps Gateway — Architecture Reference

Unified technical reference for Phases 1–5 (implemented) and the production roadmap.

## Current Posture

| Signal | State |
|--------|-------|
| Tests | 118+ passing |
| Postgres persistence | Live — requests, spans, token_usage, pricing, api_keys |
| Auth / rate limit | Middleware → `request.state` → `GatewayService` |
| Background jobs | arq workers (optional via `USE_ARQ_WORKERS`) |

---

## Phase 1: Core Async Gateway & Lifecycle

**Pattern:** Application factory + lifespan-owned dependency graph; thin HTTP adapters.

- **Entry:** `main.py` — `create_app()`, `lifespan()` wires one pool per resource on `app.state`
- **HTTPX:** `clients/http_pool.py` — `Limits(max_connections=200, max_keepalive_connections=50)` per provider
- **DTOs:** `ChatRequest`, `ChatResponse`, `ModelIdentifier` in `domain/entities/`
- **SSE:** `api/v1/chat.py` frames OpenAI-compatible `text/event-stream` with trailing usage/cost event

**Middleware order (request phase):** RequestContext → Auth → RateLimit

---

## Phase 2: Multi-Provider Resilience

**Pattern:** Template method (`BaseLLMProvider`) + cross-provider orchestration (`RoutingService`).

- **Exceptions:** `ProviderRateLimitedError`, `ProviderTimeoutError`, `ProviderConnectionError`, `ProviderResponseError`, `ProviderUnavailableError`
- **Backoff:** `Retry-After` on 429; else exponential `0.5 * 2^attempt` capped at 20s + jitter
- **Circuit breaker:** CLOSED → OPEN (5 failures) → HALF_OPEN probe after 30s cooldown
- **Routing:** `_resolve_attempts()` — native provider first, then `provider_fallback_chain`; cross-model via `provider_model_fallback_map`
- **Streaming:** no retry after first chunk yielded

---

## Phase 3: Dual-Layer Caching

**Pattern:** Port/adapter (`CacheStore`) + orchestrator (`CacheService`) + deterministic hashing.

```
lookup() → L1 Redis exact → L2 Qdrant semantic (threshold 0.95) → MISS
semantic hit → fire-and-forget L1 backfill
```

**Keys:**
- Exact: `cache:exact:{sha256(normalized_prompt|params)}:tenant:{tenant_id}`
- Coalescing lock: `lock:{exact_cache_key}:tenant:{tenant_id}` (non-stream only)
- Qdrant filter: `tenant_id`, `model_family`, `params_hash`

**Embeddings:** `sentence-transformers` via `asyncio.to_thread`, warmed at startup.

---

## Phase 4: Observability & Tracing

**Pattern:** Span context manager + async persistence/export off hot path.

**Spans:** `cache_lookup`, `upstream_call`, `cost_calculation`

**Persistence (single UoW):**
```
RequestRepository → SpanRepository.bulk_create → TokenUsageRepository
```

**Cost:** `model_pricing` table + Redis cache `pricing:{provider}:{model}` (TTL 300s). Cache hits → `cost_usd=0`.

**Export:** OTel OTLP + optional Langfuse REST ingestion.

**Metrics:** Prometheus at `/metrics` — latency histogram, cache hits, provider calls, cumulative cost.

---

## Phase 5: Middleware & Security

**API keys:** peppered SHA-256 at rest; Redis principal cache `auth:v1:{hash}` (TTL 300s).

**Scopes:** `chat:write`, `embeddings:write`, `admin:read`, `admin:write`, `*`

**Rate limit:** Redis token bucket `ratelimit:tenant:{id}` — WATCH/MULTI atomicity; 429 + `Retry-After`.

**Errors:** structured JSON with `trace_id` for 401/403/429/502/503.

---

## Phase 6: Production Infrastructure (implemented)

- Real `/health/ready` — Postgres `SELECT 1`, Redis `PING`, Qdrant health; 503 on failure
- Docker healthchecks for gateway, worker, qdrant
- `scripts/docker-entrypoint.sh` — Alembic migrate + production secret guardrails
- `make up` starts full stack including gateway and worker

---

## Phase 7: Async Worker Offload (implemented)

When `USE_ARQ_WORKERS=true` (default), gateway enqueues:
- `persist_trace` — idempotent Postgres write keyed by `trace_id`
- `export_otel_spans` — OTel/Langfuse export
- `backfill_cache` — Redis + Qdrant write-back

Falls back to in-process `asyncio.create_task` when disabled.

---

## Phase 8: Admin & Ops APIs (implemented)

- `GET/POST /v1/admin/tenants` — list / create tenants
- `GET /v1/admin/pricing` — list active pricing
- `POST /v1/admin/pricing` — create pricing row
- `GET /v1/admin/api-keys` — list keys for authenticated tenant
- `POST /v1/admin/api-keys` — mint key (returns raw key once)
- `DELETE /v1/admin/api-keys/{id}` — revoke key + invalidate auth cache

---

## Known Gaps

- Streaming client disconnect mid-response is not traced
- `provider_health` and `cache_entries_meta` tables exist but are not yet written at runtime
- Budget enforcement (`tenants.budget_monthly_usd`) not implemented
