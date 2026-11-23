#!/usr/bin/env bash
# Uso: BASE_URL=http://localhost:8080 AGENT_API_KEY=xxx ./scripts/smoke_test.sh
set -euo pipefail
: "${BASE_URL:?Define BASE_URL}"; : "${AGENT_API_KEY:?Define AGENT_API_KEY}"
echo "== healthz";     curl -s "$BASE_URL/healthz"; echo
echo "== agent card";  curl -s "$BASE_URL/.well-known/agent-card.json" | head -c 300; echo; echo
echo "== respuesta (sin streaming)"
curl -s -X POST "$BASE_URL/v1/responses" \
  -H "Authorization: Bearer $AGENT_API_KEY" -H "Content-Type: application/json" \
  -d '{"input":"¿Cuál es el proyecto de IA con mayor impacto de Ariel?"}' \
  | python3 -c "import sys,json; r=json.load(sys.stdin); print(r.get('error') or r['output'][0]['content'][0]['text']); print('usage:', r.get('usage'))"
echo; echo "== streaming (primeros eventos)"
curl -sN -X POST "$BASE_URL/v1/responses" \
  -H "Authorization: Bearer $AGENT_API_KEY" -H "Content-Type: application/json" \
  -d '{"input":"¿Cómo puedo contactarlo?","stream":true}' | grep '^event:' | uniq -c
