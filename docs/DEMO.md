# Demo Guide (≈5 minutes live, ≈2 minutes recorded)

Use this script to show the gateway behaving like a **production system**, not a thin OpenAI proxy.

## Prerequisites

```bash
cp .env.example .env
# Add OPENAI_API_KEY and/or ANTHROPIC_API_KEY to .env
make install
make up          # full stack: postgres, redis, qdrant, gateway, worker
# migrations run automatically on gateway start (RUN_MIGRATIONS_ON_STARTUP=true)
```

Dev API key (after migrations): `llmops_dev_default_key`  
Header: `X-API-Key: llmops_dev_default_key`

## One-command demo

```bash
chmod +x scripts/demo.sh
./scripts/demo.sh
```

Optional: lower rate limit for a faster 429 demo — set `DEFAULT_RATE_LIMIT_PER_MINUTE=5` in `.env` and restart gateway.

## What to show on camera (recommended order)

### 1. Architecture (30s)

Open [README system diagram](../README.md#system-overview) or `docs/ARCHITECTURE.md`. Say:

> "Requests hit auth and rate limiting first, then a dual-layer cache before any upstream LLM call. Traces and cost are persisted asynchronously via arq workers."

### 2. Health & readiness (30s)

```bash
curl -s http://localhost:8000/health | jq
curl -s http://localhost:8000/health/ready | jq
```

Point out per-dependency status: `postgres`, `redis`, `qdrant`.

### 3. Security — 401 without key (20s)

```bash
curl -s -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hi"}]}' | jq
```

Expect `error: unauthorized` and a `trace_id`.

### 4. Cache — MISS then EXACT_HIT (60s)

```bash
export KEY=llmops_dev_default_key
export BODY='{"model":"gpt-4o-mini","messages":[{"role":"user","content":"What is 2+2?"}]}'

# First call — upstream (MISS), note X-Cache-Status and X-Request-Cost
curl -si -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" -H "X-API-Key: $KEY" -d "$BODY" \
  | grep -iE '^(HTTP|x-cache-status|x-request-cost|x-trace-id)'

# Second identical call — EXACT_HIT, cost should be 0
curl -si -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" -H "X-API-Key: $KEY" -d "$BODY" \
  | grep -iE '^(HTTP|x-cache-status|x-request-cost|x-trace-id)'
```

### 5. Rate limit — 429 (30s)

Burst requests until `429` (or use `DEFAULT_RATE_LIMIT_PER_MINUTE=5`):

```bash
for i in {1..10}; do
  code=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/v1/chat/completions \
    -H "Content-Type: application/json" -H "X-API-Key: $KEY" -d "$BODY")
  echo "request $i → $code"
done
```

Show `Retry-After` header on 429.

### 6. Failure handling — readiness degrades (30s)

```bash
docker compose stop redis
curl -s http://localhost:8000/health/ready | jq   # expect status: degraded, HTTP 503
docker compose start redis
```

### 7. Observability (optional, 30s)

- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (admin/admin)
- Gateway metrics: http://localhost:8000/metrics (unauthenticated in local dev)

## Talking points while demo runs

- **Tenant isolation:** cache keys and Qdrant filters include `tenant_id`.
- **Cost attribution:** `X-Request-Cost` is zero on cache hits by design.
- **Resilience:** circuit breakers and cross-provider fallback (see `docs/DESIGN_DECISIONS.md`).
- **Tests:** `make test` — 127+ unit tests including auth, cache, rate limits.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| 502 on chat | Add `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` to `.env`, restart gateway |
| 401 with dev key | Run `make migrate` or ensure gateway entrypoint ran migrations |
| Gateway not up | `docker compose ps`, `docker compose logs gateway` |
| Slow first request | Embedding model warm-up at startup; first cache miss calls upstream |
