#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi

BASE_URL="${SMOKE_BASE_URL:-http://127.0.0.1:${BACKEND_HOST_PORT:-8000}}"
USER_ID="${SMOKE_USER_ID:-}"
PASSWORD="${SMOKE_PASSWORD:-}"
DEVICE_ID="${SMOKE_DEVICE_ID:-}"
TIMEOUT_SECONDS="${SMOKE_TIMEOUT_SECONDS:-15}"

usage() {
  cat <<'EOF'
Usage:
  SMOKE_USER_ID=<user_id> SMOKE_PASSWORD=<password> SMOKE_DEVICE_ID=<device_id> ./scripts/smoke-api.sh

Optional environment:
  SMOKE_BASE_URL=http://127.0.0.1:18000
  SMOKE_TIMEOUT_SECONDS=15

Checks:
  - /health
  - /live
  - /ready
  - POST /api/v1/auth/login
  - GET /api/v1/me/devices
  - GET /api/v1/devices/{device_id}
  - GET /api/v1/devices/{device_id}/linked-users
  - GET /api/v1/devices/{device_id}/latest
  - GET /api/v1/devices/{device_id}/history
  - GET /api/v1/devices/{device_id}/summary
  - GET /api/v1/public/devices/{device_id}/summary
EOF
}

if [[ -z "$USER_ID" || -z "$PASSWORD" || -z "$DEVICE_ID" ]]; then
  usage
  exit 1
fi

pass() {
  printf '[PASS] %s\n' "$1"
}

curl_json() {
  local method="$1"
  local url="$2"
  local token="${3:-}"
  local body="${4:-}"
  local -a args
  args=(
    --silent
    --show-error
    --fail
    --max-time "$TIMEOUT_SECONDS"
    -X "$method"
    "$url"
  )

  if [[ -n "$token" ]]; then
    args+=(-H "Authorization: Bearer $token")
  fi
  if [[ -n "$body" ]]; then
    args+=(-H "Content-Type: application/json" -d "$body")
  fi

  curl "${args[@]}"
}

assert_json() {
  local json_payload="$1"
  local python_code="$2"
  JSON_PAYLOAD="$json_payload" DEVICE_ID="$DEVICE_ID" USER_ID="$USER_ID" python3 -c "$python_code"
}

printf 'Smoke test target: %s\n' "$BASE_URL"

health_json="$(curl_json GET "$BASE_URL/health")"
assert_json "$health_json" \
  'import json, os; data=json.loads(os.environ["JSON_PAYLOAD"]); assert data.get("status") == "ok"; assert data.get("database") == "connected"'
pass "/health"

ready_json="$(curl_json GET "$BASE_URL/ready")"
assert_json "$ready_json" \
  'import json, os; data=json.loads(os.environ["JSON_PAYLOAD"]); assert data.get("status") == "ok"; assert data.get("database") == "connected"'
pass "/ready"

live_json="$(curl_json GET "$BASE_URL/live")"
assert_json "$live_json" \
  'import json, os; data=json.loads(os.environ["JSON_PAYLOAD"]); assert data.get("status") == "alive"'
pass "/live"

login_payload="$(USER_ID="$USER_ID" PASSWORD="$PASSWORD" python3 - <<'PY'
import json
import os
print(json.dumps({"user_id": os.environ["USER_ID"], "password": os.environ["PASSWORD"]}))
PY
)"
login_json="$(curl_json POST "$BASE_URL/api/v1/auth/login" "" "$login_payload")"
assert_json "$login_json" \
  'import json, os; data=json.loads(os.environ["JSON_PAYLOAD"]); assert data.get("user_id") == os.environ["USER_ID"]; assert data.get("token_type") == "bearer"; assert data.get("access_token")'
TOKEN="$(JSON_PAYLOAD="$login_json" python3 - <<'PY'
import json
import os
print(json.loads(os.environ["JSON_PAYLOAD"])["access_token"])
PY
)"
pass "POST /api/v1/auth/login"

me_devices_json="$(curl_json GET "$BASE_URL/api/v1/me/devices" "$TOKEN")"
assert_json "$me_devices_json" \
  'import json, os; data=json.loads(os.environ["JSON_PAYLOAD"]); assert any(item.get("device_id") == os.environ["DEVICE_ID"] for item in data.get("items", []))'
pass "GET /api/v1/me/devices"

device_json="$(curl_json GET "$BASE_URL/api/v1/devices/$DEVICE_ID" "$TOKEN")"
assert_json "$device_json" \
  'import json, os; data=json.loads(os.environ["JSON_PAYLOAD"]); assert data.get("device_id") == os.environ["DEVICE_ID"]'
pass "GET /api/v1/devices/{device_id}"

linked_users_json="$(curl_json GET "$BASE_URL/api/v1/devices/$DEVICE_ID/linked-users" "$TOKEN")"
assert_json "$linked_users_json" \
  'import json, os; data=json.loads(os.environ["JSON_PAYLOAD"]); assert any(item.get("user_id") == os.environ["USER_ID"] for item in data.get("items", []))'
pass "GET /api/v1/devices/{device_id}/linked-users"

latest_json="$(curl_json GET "$BASE_URL/api/v1/devices/$DEVICE_ID/latest" "$TOKEN")"
assert_json "$latest_json" \
  'import json, os; data=json.loads(os.environ["JSON_PAYLOAD"]); assert data.get("device_id") == os.environ["DEVICE_ID"]'
pass "GET /api/v1/devices/{device_id}/latest"

history_json="$(curl_json GET "$BASE_URL/api/v1/devices/$DEVICE_ID/history?limit=5" "$TOKEN")"
assert_json "$history_json" \
  'import json, os; data=json.loads(os.environ["JSON_PAYLOAD"]); assert data.get("count", 0) >= 1; assert any(item.get("device_id") == os.environ["DEVICE_ID"] for item in data.get("items", []))'
pass "GET /api/v1/devices/{device_id}/history"

summary_json="$(curl_json GET "$BASE_URL/api/v1/devices/$DEVICE_ID/summary?period=24h" "$TOKEN")"
assert_json "$summary_json" \
  'import json, os; data=json.loads(os.environ["JSON_PAYLOAD"]); assert data.get("device_id") == os.environ["DEVICE_ID"]; assert data.get("total_readings", 0) >= 1; assert "summary" in data'
pass "GET /api/v1/devices/{device_id}/summary"

public_summary_json="$(curl_json GET "$BASE_URL/api/v1/public/devices/$DEVICE_ID/summary?period=24h" "$TOKEN")"
assert_json "$public_summary_json" \
  'import json, os; data=json.loads(os.environ["JSON_PAYLOAD"]); assert data.get("device_id") == os.environ["DEVICE_ID"]; assert data.get("total_readings", 0) >= 1'
pass "GET /api/v1/public/devices/{device_id}/summary"

printf 'Smoke test completed successfully for device %s and user %s\n' "$DEVICE_ID" "$USER_ID"
