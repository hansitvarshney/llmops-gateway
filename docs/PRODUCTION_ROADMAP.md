# Production Roadmap

Honest gaps and next steps — useful for interviews and README transparency.

## Shipped in v1.0.0-beta.1

- [x] Multi-provider gateway with circuit breakers and fallback chains
- [x] Dual-layer cache (Redis + Qdrant semantic)
- [x] Multi-tenant API key auth, scopes, rate limiting
- [x] Trace + cost persistence (Postgres), OTel/Prometheus
- [x] arq workers for trace export and cache backfill
- [x] Readiness/liveness, Docker healthchecks, migrate-on-start
- [x] Admin APIs (tenants, pricing, API keys)

## Next (high impact)

| Priority | Item | Why |
|----------|------|-----|
| P0 | **Cloud deploy** (Fly/Railway/AWS) + public demo URL | Recruiter-visible proof |
| P0 | **Benchmark numbers** in README (`scripts/benchmark_gateway.py`) | Quantified impact |
| P0 | **2-min demo video** (`docs/DEMO.md`) | Human proof of ownership |
| P1 | Streaming disconnect tracing | Close known observability gap |
| P1 | `cache_entries_meta` + Qdrant GC cron | Operational hygiene at scale |
| P1 | Per-tenant `rate_limit_per_minute` in DB | Sales/ops configurability |
| P2 | Budget enforcement (`budget_monthly_usd`) | FinOps |
| P2 | Persisted `provider_health` | Cross-replica circuit awareness |
| P2 | Embeddings passthrough endpoint | Feature completeness |
| P3 | Load tests (Locust) in CI | Performance regression signal |

## Production checklist (before real traffic)

- [ ] Rotate `AUTH_API_KEY_PEPPER`; remove/skip dev seed key migration in prod
- [ ] Set `ENVIRONMENT=production`
- [ ] Lock down `/metrics`, `/docs` behind ingress auth or disable
- [ ] Configure real TLS termination at load balancer
- [ ] Set up DB backups and connection limits
- [ ] Alert on `/health/ready` 503 and provider error rate
