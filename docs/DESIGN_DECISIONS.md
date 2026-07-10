# Design Decisions & Interview Prep

Architecture Decision Records (lightweight) and likely interview questions for this project.

---

## ADR-1: Dual-layer cache (Redis exact + Qdrant semantic)

**Decision:** Layer 1 exact match in Redis; Layer 2 cosine similarity in Qdrant (threshold ≥ 0.95), filtered by `tenant_id`, `model_family`, `params_hash`.

**Why not one layer?**
- Exact match is O(1), sub-millisecond, cheap — handles repeat prompts.
- Semantic match catches paraphrases but needs embeddings + vector search (higher latency, infra cost).

**Tradeoffs:**
- (+) Higher hit rate than exact-only; lower cost than always calling upstream.
- (−) Semantic false positives possible near threshold; mitigated by strict filters and 0.95 cutoff.
- (−) Collection per embedding model — versioned when model changes.

**Interview sound bite:** *"We treat exact and semantic as complementary SLO tiers — speed vs recall."*

---

## ADR-2: Fail-closed cache on backend errors

**Decision:** Redis/Qdrant timeouts or errors → treat as cache MISS, never raise to client.

**Why:** A cache outage must not take down the gateway; worst case is extra upstream spend.

**Tradeoff:** Under Redis degradation, thundering herd to providers — mitigated by request coalescing (non-stream).

---

## ADR-3: In-process circuit breaker vs persisted `provider_health`

**Decision:** Circuit breaker state lives in memory per provider adapter (`CLOSED` → `OPEN` → `HALF_OPEN`).

**Why:** Fast, no DB round-trip on every request; good for single-process or horizontally scaled instances with independent breakers.

**Tradeoff:** New pod doesn't inherit cluster-wide failure state — acceptable for beta; `provider_health` table reserved for future shared state.

**Interview question:** *"How would you share circuit state across replicas?"*  
→ Redis/etcd with short TTL, or outlier detection at load balancer; persist opens for ops dashboards only.

---

## ADR-4: Cross-provider fallback in `RoutingService`, not in adapters

**Decision:** `BaseLLMProvider` retries same provider; `RoutingService` tries next provider/model in chain.

**Why:** Separation of concerns — adapter owns transport resilience; router owns business-level failover.

**Streaming rule:** No fallback after first chunk — prevents duplicate tokens to client.

---

## ADR-5: arq workers vs in-process `asyncio.create_task`

**Decision:** Default `USE_ARQ_WORKERS=true` — trace persist, OTel export, cache backfill enqueued to Redis; fallback to in-process tasks if enqueue fails or disabled.

**Why:**
- Survives process crash after response sent (at-least-once retry).
- Keeps hot path free of Postgres/Qdrant write latency.

**Tradeoffs:**
- (+) Production-shaped async boundary.
- (−) Extra moving part (worker process); Redis as job broker.

**Idempotency:** `persist_trace` skips if `trace_id` already exists — safe under arq retries.

---

## ADR-6: Peppered SHA-256 for API keys (not bcrypt)

**Decision:** Store `sha256(pepper + raw_key)`; verify with `secrets.compare_digest`.

**Why:** API keys are high-entropy generated tokens (not user passwords) — slow KDF less critical; O(1) lookup by hash index.

**Tradeoff:** Compromise of pepper + DB exposes all keys — pepper must be a real secret in production (`AUTH_API_KEY_PEPPER` guardrail).

**Interview question:** *"Why not bcrypt?"*  
→ For user passwords, yes. For 256-bit random API keys, SHA-256 + pepper + TLS in transit is industry-acceptable (similar to how many API gateways store key fingerprints).

---

## ADR-7: Redis token bucket with WATCH/MULTI (not Lua)

**Decision:** Optimistic locking with `WATCH`/`MULTI`/`EXEC` for per-tenant rate limits.

**Why:** Works with fakeredis in tests; no Lua dependency; sufficient at expected scale.

**Tradeoff:** Contention under extreme parallel load on one tenant — retry loop (max 5) then treat as limited.

---

## ADR-8: Cross-dialect ORM (`Uuid`, `JSON`) for SQLite tests

**Decision:** Avoid Postgres-only types in models so repositories run against in-memory SQLite in CI without Docker.

**Why:** Fast, deterministic tests for auth, tracing, pricing repos — real SQL, not mocks.

---

## ADR-9: Readiness vs liveness

**Decision:**
- `/health` — always 200 if process up (liveness).
- `/health/ready` — probes Postgres, Redis, Qdrant; 503 if any dependency unhealthy (readiness).

**Why:** Orchestrators (K8s, Compose) can restart on liveness; remove from LB on readiness failure.

---

## Likely interview questions

### "Walk me through a request."

1. `RequestContextMiddleware` assigns `trace_id`.
2. `AuthMiddleware` validates `X-API-Key`, scopes, sets `tenant_id`.
3. `RateLimitMiddleware` token bucket per tenant.
4. `GatewayService`: cache lookup (Redis → Qdrant) → optional coalescing lock → `RoutingService` → cost calc.
5. `_finalize`: Prometheus metrics sync; arq enqueue for trace persist + export + cache backfill.

### "How do you prevent cross-tenant cache leakage?"

Tenant ID in Redis key suffix and Qdrant payload filter; auth middleware binds tenant from API key, not client body.

### "What happens on provider 429?"

Adapter retries with backoff / `Retry-After`; if exhausted, `RoutingService` tries fallback provider; if all fail → 503 `AllProvidersExhaustedError`.

### "How is cost calculated on cache hits?"

`cost_usd=0` — no new upstream tokens consumed; pricing table used only on misses.

### "What would you do next for production?"

See [PRODUCTION_ROADMAP.md](PRODUCTION_ROADMAP.md) — streaming disconnect tracing, `cache_entries_meta` GC, per-tenant rate limits in DB, budget enforcement, load testing, cloud deploy.

### "How do you test this?"

127+ pytest tests: provider adapters (mocked httpx), cache (fakeredis, Qdrant memory), auth middleware (ASGI), repositories (SQLite), rate limiter, tracing idempotency.

---

## Red flags to avoid in interviews

- Don't claim "production-ready" without mentioning streaming disconnect gap and unused schema tables.
- Don't say semantic cache replaces exact cache — they stack.
- Don't confuse OTel HTTP instrumentation spans with business spans (`cache_lookup`, etc.) — both exist, different purposes.
