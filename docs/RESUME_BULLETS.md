# Resume & LinkedIn Copy

Copy-paste bullets for different audiences. Replace bracketed placeholders after running benchmarks.

---

## One-line pitch

**LLMOps Gateway** — async multi-tenant LLM gateway (FastAPI) with dual-layer semantic caching, OpenAI/Anthropic failover, per-request cost/tracing, and Redis-backed rate limiting; 127+ tests, Dockerized, arq workers.

---

## Resume bullets — Backend / Platform Engineer (recommended)

- Built an **async FastAPI LLM gateway** with OpenAI + Anthropic adapters, **circuit breakers**, exponential backoff, and **cross-provider fallback routing** for resilient upstream calls.
- Implemented **dual-layer caching** (Redis exact-match + Qdrant semantic similarity at 0.95 cosine) with tenant-scoped keys, request coalescing on cache miss, and **$0 cost attribution on cache hits**.
- Designed **multi-tenant security**: peppered SHA-256 API keys, Redis-cached auth principals, scope-based route access, and **per-tenant token-bucket rate limiting** (429 + Retry-After).
- Shipped **observability stack**: OpenTelemetry + Prometheus metrics, Postgres trace persistence (requests/spans/token usage), versioned **model pricing** with Redis cache-aside, optional Langfuse export.
- Hardened for deployment: **readiness probes** (Postgres/Redis/Qdrant), Docker healthchecks, Alembic migrate-on-start, **arq background workers** for async trace/cache offload; **127+ unit tests**.

---

## Resume bullets — ML / LLMOps / AI Platform

- Developed an **LLMOps inference gateway** intercepting all LLM traffic for **cache optimization**, cost tracking, and audit logging across tenants.
- Reduced redundant upstream spend via **semantic cache** (sentence-transformers embeddings + Qdrant) and exact Redis layer; exposed hit status via `X-Cache-Status` and **per-request cost** via `X-Request-Cost`.
- Integrated **pluggable embedding backend** (local `sentence-transformers` or API) with collection versioning per model; similarity-gated retrieval with tenant/model/param filters.
- Persisted **request traces and token usage** to PostgreSQL with idempotent `trace_id` writes; async export to OTel/Langfuse pipelines off the hot path.

---

## Resume bullets — With metrics (fill after `make benchmark`)

Run `python scripts/benchmark_gateway.py --requests 20` and paste your numbers:

- Architected LLM gateway achieving **[X]% cache hit ratio** on repeated workloads, **p50 [Y] ms / p95 [Z] ms** latency (local Docker), with **zero marginal cost** on exact cache hits.
- [Keep 2–3 bullets from Backend section above]

---

## LinkedIn — Featured project (short)

**LLMOps Gateway & Observability Platform**  
Production-shaped async gateway for OpenAI/Anthropic: dual-layer semantic caching (Redis + Qdrant), multi-tenant API keys, rate limiting, circuit breakers with provider failover, and full request tracing + cost attribution to Postgres.  
Stack: FastAPI, PostgreSQL, Redis, Qdrant, OpenTelemetry, Prometheus, arq, Docker.  
GitHub: https://github.com/hansitvarshney/llmops-gateway

---

## LinkedIn — About section snippet (optional)

I build platform infrastructure for LLM applications — not just prompts. Recent work: a multi-tenant gateway with semantic caching, observability, and resilience patterns (circuit breakers, fallback chains, async workers) tested with 127+ unit tests.

---

## GitHub repo description (≤350 chars)

Async multi-tenant LLM gateway: Redis+Qdrant semantic cache, OpenAI/Anthropic failover, OTel tracing, cost attribution, API-key auth, rate limits. FastAPI · Postgres · arq · Docker

**Topics:** `fastapi` `llm` `observability` `redis` `qdrant` `opentelemetry` `semantic-caching` `platform-engineering` `python`

---

## Cover letter paragraph

For my LLMOps Gateway project, I focused on problems teams hit after the first OpenAI prototype: runaway API cost, no visibility into per-tenant usage, and fragile single-provider integrations. I built an async FastAPI gateway with dual-layer caching (exact + semantic), multi-tenant authentication, rate limiting, and a full observability pipeline — traces, token usage, and versioned pricing persisted to PostgreSQL, with background workers keeping the request path fast. The codebase reflects how I think about production systems: fail-closed caches, idempotent workers, readiness probes, and broad automated tests rather than demo-only happy paths.
