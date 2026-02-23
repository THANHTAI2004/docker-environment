#!/bin/bash
# API endpoint helper for local + Cloudflare Tunnel deployment.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

IP=$(hostname -I | awk '{print $1}')
if [ -z "${IP}" ]; then
  echo "Khong lay duoc IP may chu."
  exit 1
fi

CLOUDFLARE_URL=""
BACKEND_HOST_PORT="8000"
if [ -f "${ENV_FILE}" ]; then
  CLOUDFLARE_URL=$(grep -E '^CLOUDFLARE_PUBLIC_URL=' "${ENV_FILE}" | cut -d'=' -f2- || true)
  BACKEND_HOST_PORT=$(grep -E '^BACKEND_HOST_PORT=' "${ENV_FILE}" | cut -d'=' -f2- || true)
fi
BACKEND_HOST_PORT=${BACKEND_HOST_PORT:-8000}

QUICK_CLOUDFLARE_URL=""
if command -v docker >/dev/null 2>&1; then
  QUICK_CLOUDFLARE_URL=$(docker logs cloudflared-quick 2>&1 | grep -Eo 'https://[-a-z0-9]+\.trycloudflare\.com' | tail -n 1 || true)
fi

echo "Thong tin endpoint server:"
echo "  Local API:      http://${IP}:${BACKEND_HOST_PORT}"

if [ -n "${CLOUDFLARE_URL}" ]; then
  echo "  Public API:     ${CLOUDFLARE_URL}"
  echo ""
  echo "ESP32:"
  echo "  API_BASE = \"${CLOUDFLARE_URL}\""
  echo ""
  echo "Flutter:"
  echo "  baseUrl = \"${CLOUDFLARE_URL}\""
elif [ -n "${QUICK_CLOUDFLARE_URL}" ]; then
  echo "  Public API:     ${QUICK_CLOUDFLARE_URL} (quick tunnel)"
  echo ""
  echo "ESP32:"
  echo "  API_BASE = \"${QUICK_CLOUDFLARE_URL}\""
  echo ""
  echo "Flutter:"
  echo "  baseUrl = \"${QUICK_CLOUDFLARE_URL}\""
else
  echo "  Public API:     (chua cau hinh CLOUDFLARE_PUBLIC_URL trong .env)"
  echo ""
  echo "ESP32/Flutter test LAN:"
  echo "  API_BASE/baseUrl = \"http://${IP}:${BACKEND_HOST_PORT}\""
fi
