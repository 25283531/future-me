#!/usr/bin/env bash
# Curl smoke test: starts the server on a temp port with a temp DATA_DIR,
# exercises the key endpoints, then stops it.
# Usage: bash scripts/smoke.sh   (run from backend/)
set -euo pipefail

cd "$(dirname "$0")/.."
export DATA_DIR="$(mktemp -d /tmp/futureme-smoke-XXXXXX)"
export JWT_SECRET="smoke-secret"
# API keys are no longer read from env vars (they live in the admin console).
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

echo "== privacy page + JSON =="
curl -fsS "$BASE/privacy" | grep -q "隐私协议" && echo "ok: /privacy serves the policy"
curl -fsS "$BASE/api/v1/privacy" -H "Authorization: Bearer $TOKEN" | grep -q "加密" && echo "ok: /api/v1/privacy serves the policy text"

echo "== captcha + register (no SMTP: account usable unverified) =="
CAPTCHA_JSON=$(curl -fsS "$BASE/api/v1/auth/captcha")
CHALLENGE=$(echo "$CAPTCHA_JSON" | "$PY" -c 'import sys,json;print(json.load(sys.stdin)["challenge_id"])')
echo "$CAPTCHA_JSON" | grep -q "<svg" && echo "ok: captcha SVG returned"
# wrong captcha answer must fail (challenge is single-use, so this also consumes it)
curl -s -o /dev/null -w 'wrong captcha: %{http_code}\n' -X POST "$BASE/api/v1/auth/register" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"smoke@example.com\",\"password\":\"password123\",\"device_id\":\"smoke-device-curl\",\"captcha_challenge_id\":\"$CHALLENGE\",\"captcha_answer\":\"ZZZZ\"}"

echo "== admin: unauthenticated dashboard rejected (expect 401) =="
curl -s -o /dev/null -w '%{http_code}\n' "$BASE/api/v1/admin/dashboard"

echo "== admin: setup + login + dashboard + settings =="
COOKIE_JAR="$DATA_DIR/cookies.txt"
curl -fsS -c "$COOKIE_JAR" -X POST "$BASE/api/v1/admin/setup" \
  -H 'Content-Type: application/json' -d '{"password":"smoke-admin-1"}'; echo
curl -fsS -b "$COOKIE_JAR" "$BASE/api/v1/admin/dashboard"; echo
curl -fsS -b "$COOKIE_JAR" "$BASE/api/v1/admin/settings" | head -c 400; echo
# membership config via admin must be reflected in the public endpoint
curl -fsS -b "$COOKIE_JAR" -X POST "$BASE/api/v1/admin/settings" \
  -H 'Content-Type: application/json' \
  -d '{"settings":{"membership.trial_days":"14","membership.price_monthly_cny":"19.9","membership.paywalled":"1"}}' >/dev/null
curl -fsS "$BASE/api/v1/membership/status" -H "Authorization: Bearer $TOKEN"; echo
echo "== admin: privacy — dashboard must not contain the wish text =="
curl -fsS -b "$COOKIE_JAR" "$BASE/api/v1/admin/dashboard" | grep -q "教师资格证" && { echo "FAIL: wish text leaked into admin dashboard"; exit 1; } || echo "ok: no user text in dashboard"
echo "== admin: encryption — key file exists with mode 0600 =="
ls -l "$DATA_DIR/.encryption.key"
[ "$(stat -c %a "$DATA_DIR/.encryption.key")" = "600" ] || { echo "FAIL: key file mode is not 0600"; exit 1; }
echo "== admin: encryption — DB stores ciphertext, not plaintext =="
"$PY" -c "
import sqlite3
conn = sqlite3.connect('$DATA_DIR/futureme.db')
row = conn.execute('SELECT text FROM wishes').fetchone()
assert row and '教师资格证' not in row[0], 'FAIL: plaintext wish in DB'
print('ok: wish stored encrypted')
"

echo "== TTS via Edge fallback =="
TTS_JSON=$(curl -fsS -X POST "$BASE/api/v1/tts/synthesize" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"text":"你好，这是未来我的一封信。","voice_id":"edge-xiaoxiao"}')
echo "$TTS_JSON"
AUDIO_URL=$(echo "$TTS_JSON" | "$PY" -c 'import sys,json;print(json.load(sys.stdin)["audio_url"])')
curl -fsS "$AUDIO_URL" -o /tmp/smoke-audio.mp3
ls -la /tmp/smoke-audio.mp3

echo "SMOKE OK"
