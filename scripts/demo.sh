#!/usr/bin/env bash
# Reproducible 5-minute demo for recruiters / interviews.
# Prerequisites: `make up` (or `make dev` + infra), migrations applied, curl installed.
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
API_KEY="${API_KEY:-llmops_dev_default_key}"
CHAT_PAYLOAD='{"model":"gpt-4o-mini","messages":[{"role":"user","content":"What is 2+2?"}]}'

section() { echo ""; echo "=== $1 ==="; }

require_curl() {
  command -v curl >/dev/null || { echo "curl is required"; exit 1; }
}

require_curl

section "1. Liveness — GET /health"
curl -sf "$BASE_URL/health" | python3 -m json.tool

section "2. Readiness — GET /health/ready (all deps healthy)"
curl -sf "$BASE_URL/health/ready" | python3 -m json.tool

section "3. Auth — missing API key → 401"
curl -s -o /tmp/llmops_demo_401.json -w "HTTP %{http_code}\n" \
  -X POST "$BASE_URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "$CHAT_PAYLOAD" || true
python3 -m json.tool < /tmp/llmops_demo_401.json 2>/dev/null || cat /tmp/llmops_demo_401.json

section "4. Chat — first request (cache MISS or upstream call)"
echo "Requires OPENAI_API_KEY or ANTHROPIC_API_KEY in gateway .env"
RESP1=$(curl -s -D /tmp/llmops_demo_h1.txt -o /tmp/llmops_demo_b1.json -w "%{http_code}" \
  -X POST "$BASE_URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d "$CHAT_PAYLOAD") || true
echo "HTTP $RESP1"
grep -iE '^(x-trace-id|x-cache-status|x-request-cost):' /tmp/llmops_demo_h1.txt || true
head -c 400 /tmp/llmops_demo_b1.json; echo ""

section "5. Chat — identical request (expect EXACT_HIT if step 4 succeeded)"
RESP2=$(curl -s -D /tmp/llmops_demo_h2.txt -o /tmp/llmops_demo_b2.json -w "%{http_code}" \
  -X POST "$BASE_URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d "$CHAT_PAYLOAD") || true
echo "HTTP $RESP2"
grep -iE '^(x-trace-id|x-cache-status|x-request-cost):' /tmp/llmops_demo_h2.txt || true

section "6. Rate limit — burst requests (may return 429)"
echo "Tip: set DEFAULT_RATE_LIMIT_PER_MINUTE=5 in .env for a faster 429 demo"
for i in $(seq 1 8); do
  CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "$BASE_URL/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $API_KEY" \
    -d "$CHAT_PAYLOAD") || true
  echo "  request $i → HTTP $CODE"
  if [ "$CODE" = "429" ]; then
    curl -s -D - -o /dev/null \
      -X POST "$BASE_URL/v1/chat/completions" \
      -H "Content-Type: application/json" \
      -H "X-API-Key: $API_KEY" \
      -d "$CHAT_PAYLOAD" 2>/dev/null | grep -i retry-after || true
    break
  fi
done

section "7. Readiness degradation (manual)"
cat <<'EOF'
Run in another terminal to show 503 on /health/ready:
  docker compose stop redis
  curl -s http://localhost:8000/health/ready | python3 -m json.tool
  docker compose start redis
EOF

section "Done"
echo "Record steps 1–6 (and optionally 7) for a ~2 minute demo video."
echo "Full walkthrough: docs/DEMO.md"
