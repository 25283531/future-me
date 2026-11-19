#!/usr/bin/env bash
# Curl smoke test: starts the server on a temp port with a temp DATA_DIR,
# exercises the key endpoints, then stops it.
# Usage: bash scripts/smoke.sh   (run from backend/)
set -euo pipefail

cd "$(dirname "$0")/.."
export DATA_DIR="$(mktemp -d /tmp/futureme-smoke-XXXXXX)"
export JWT_SECRET="smoke-secret"
unset DASHSCOPE_API_KEY ZHISHU_API_KEY HUNYUAN_API_KEY SILICONFLOW_API_KEY GENERIC_LLM_API_KEY GENERIC_LLM_BASE_URL GENERIC_LLM_MODEL TENCENT_SECRET_ID TENCENT_SECRET_KEY || true
PORT="${SMOKE_PORT:-18080}"

PY=".venv/bin/python"
if [ ! -x "$PY" ]; then PY="python3"; fi

"$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" >"$DATA_DIR/server.log" 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null; rm -rf "$DATA_DIR"' EXIT

BASE="http://127.0.0.1:$PORT"
for _ in $(seq 1 30); do
  curl -fsS "$BASE/api/v1/health" >/dev/null 2>&1 && break
  sleep 0.5
done

echo "== health =="
curl -fsS "$BASE/api/v1/health"; echo

echo "== device auth =="
TOKEN=$(curl -fsS -X POST "$BASE/api/v1/auth/device" \
  -H 'Content-Type: application/json' \
  -d '{"device_id":"smoke-device-curl"}' | "$PY" -c 'import sys,json;print(json.load(sys.stdin)["token"])')
echo "token: ${TOKEN:0:20}..."

echo "== create wish =="
WISH_ID=$(curl -fsS -X POST "$BASE/api/v1/wishes" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"text":"90天后通过教师资格证考试","category":"学习考证","days":90}' \
  | "$PY" -c 'import sys,json;print(json.load(sys.stdin)["id"])')
echo "wish id: $WISH_ID"

echo "== list wishes =="
curl -fsS "$BASE/api/v1/wishes" -H "Authorization: Bearer $TOKEN"; echo

echo "== daily sentence =="
curl -fsS "$BASE/api/v1/daily-sentence" -H "Authorization: Bearer $TOKEN"; echo

echo "== checkin =="
curl -fsS -X POST "$BASE/api/v1/checkin" -H "Authorization: Bearer $TOKEN"; echo

echo "== voices (count) =="
curl -fsS "$BASE/api/v1/voices" -H "Authorization: Bearer $TOKEN" \
  | "$PY" -c 'import sys,json;print(len(json.load(sys.stdin)),"voices")'

echo "== LLM providers =="
curl -fsS "$BASE/api/v1/llm/providers" -H "Authorization: Bearer $TOKEN"; echo

echo "== letter generate without key (expect 503) =="
curl -s -o /tmp/smoke-letter.json -w '%{http_code}\n' -X POST "$BASE/api/v1/letters/generate" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"wish_id\":$WISH_ID}"
cat /tmp/smoke-letter.json; echo

echo "== membership =="
curl -fsS "$BASE/api/v1/membership/status" -H "Authorization: Bearer $TOKEN"; echo

echo "== TTS via Edge fallback =="
TTS_JSON=$(curl -fsS -X POST "$BASE/api/v1/tts/synthesize" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"text":"你好，这是未来我的一封信。","voice_id":"edge-xiaoxiao"}')
echo "$TTS_JSON"
AUDIO_URL=$(echo "$TTS_JSON" | "$PY" -c 'import sys,json;print(json.load(sys.stdin)["audio_url"])')
curl -fsS "$AUDIO_URL" -o /tmp/smoke-audio.mp3
ls -la /tmp/smoke-audio.mp3

echo "SMOKE OK"
