# Benchmarks

Run against a live local gateway with provider API keys configured.

## How to run

```bash
make up
# ensure OPENAI_API_KEY or ANTHROPIC_API_KEY is set in .env
python scripts/benchmark_gateway.py --requests 20
```

The script prints a markdown table — paste results below.

## Results (template — replace after running)

| Metric | Value |
|--------|-------|
| Requests | 20 |
| Cache hit ratio | _run benchmark_ |
| Latency p50 | _run benchmark_ |
| Latency p95 | _run benchmark_ |
| Aggregate cost (headers) | _run benchmark_ |
| Environment | local Docker, `gpt-4o-mini` |
| Date | _YYYY-MM-DD_ |

## Example interpretation

- **Request 1:** `MISS` — pays upstream latency + cost.
- **Requests 2–N:** `EXACT_HIT` — near-zero marginal cost, lower latency.
- **Hit ratio** on identical prompts should approach 100% after warm-up.
- **Semantic hits** require paraphrased prompts (not measured by default script).

## Notes

- First request after gateway restart may be slower (embedding model warm-up).
- Cache hits report `X-Request-Cost: 0.000000` by design.
- For load testing at scale, see `tests/load/` (Locust scaffold).
