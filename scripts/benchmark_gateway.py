#!/usr/bin/env python3
"""Measure cache hit ratio, latency, and cost headers against a running gateway.

Usage:
  python scripts/benchmark_gateway.py
  python scripts/benchmark_gateway.py --requests 20 --url http://localhost:8000

Paste the markdown table into README.md (Benchmarks section) after running.
Requires a valid API key and upstream provider credentials on the gateway.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time

import httpx

DEFAULT_PAYLOAD = {
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "Benchmark prompt: explain caching in one sentence."}],
}


def run_benchmark(
    *,
    base_url: str,
    api_key: str,
    requests: int,
    payload: dict,
) -> int:
    latencies_ms: list[float] = []
    cache_statuses: list[str] = []
    costs: list[float] = []
    errors = 0

    with httpx.Client(base_url=base_url, timeout=120.0) as client:
        for i in range(requests):
            started = time.perf_counter()
            try:
                response = client.post(
                    "/v1/chat/completions",
                    json=payload,
                    headers={"X-API-Key": api_key},
                )
                elapsed_ms = (time.perf_counter() - started) * 1000
                latencies_ms.append(elapsed_ms)

                if response.status_code >= 400:
                    errors += 1
                    print(f"  [{i + 1}/{requests}] HTTP {response.status_code}: {response.text[:120]}")
                    continue

                cache_statuses.append(response.headers.get("X-Cache-Status", "UNKNOWN"))
                cost_raw = response.headers.get("X-Request-Cost", "0")
                costs.append(float(cost_raw))
                print(
                    f"  [{i + 1}/{requests}] "
                    f"{elapsed_ms:.0f}ms "
                    f"cache={response.headers.get('X-Cache-Status')} "
                    f"cost=${cost_raw}"
                )
            except httpx.HTTPError as exc:
                errors += 1
                print(f"  [{i + 1}/{requests}] error: {exc}")

    if not latencies_ms:
        print("\nNo successful requests — check API key and provider credentials.")
        return 1

    hits = sum(1 for s in cache_statuses if s in ("EXACT_HIT", "SEMANTIC_HIT"))
    hit_ratio = hits / len(cache_statuses) if cache_statuses else 0.0

    print("\n--- Summary ---")
    print(f"Requests:     {requests} ({len(cache_statuses)} ok, {errors} errors)")
    print(f"Cache hits:   {hits}/{len(cache_statuses)} ({hit_ratio:.0%})")
    print(f"Latency p50:  {statistics.median(latencies_ms):.0f} ms")
    print(f"Latency p95:  {sorted(latencies_ms)[max(0, int(len(latencies_ms) * 0.95) - 1)]:.0f} ms")
    print(f"Total cost:   ${sum(costs):.6f} (cache hits report $0)")

    print("\n--- Paste into README (Benchmarks) ---")
    print("| Metric | Value |")
    print("|--------|-------|")
    print(f"| Requests | {requests} |")
    print(f"| Cache hit ratio | {hit_ratio:.0%} |")
    print(f"| Latency p50 | {statistics.median(latencies_ms):.0f} ms |")
    print(
        f"| Latency p95 | "
        f"{sorted(latencies_ms)[max(0, int(len(latencies_ms) * 0.95) - 1)]:.0f} ms |"
    )
    print(f"| Aggregate cost (headers) | ${sum(costs):.6f} |")
    print(f"| Environment | local Docker / {base_url} |")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark LLMOps gateway cache and latency")
    parser.add_argument("--url", default="http://localhost:8000", help="Gateway base URL")
    parser.add_argument("--api-key", default="llmops_dev_default_key", help="X-API-Key value")
    parser.add_argument("--requests", type=int, default=10, help="Identical requests to send")
    args = parser.parse_args()
    return run_benchmark(
        base_url=args.url.rstrip("/"),
        api_key=args.api_key,
        requests=args.requests,
        payload=DEFAULT_PAYLOAD,
    )


if __name__ == "__main__":
    sys.exit(main())
