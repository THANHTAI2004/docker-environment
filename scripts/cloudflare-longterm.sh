#!/bin/bash
# Start long-term deployment with Cloudflare named tunnel.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

if [ ! -f "${ENV_FILE}" ]; then
  echo "Missing ${ENV_FILE}. Create it from .env.example first."
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

if [ -z "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]; then
  echo "CLOUDFLARE_TUNNEL_TOKEN is empty."
  echo "Set token in ${ENV_FILE} to run named tunnel."
  exit 1
fi

if [ -z "${CLOUDFLARE_PUBLIC_URL:-}" ]; then
  echo "Warning: CLOUDFLARE_PUBLIC_URL is not set in ${ENV_FILE}."
  echo "Health check will only validate local API."
fi

cd "${ROOT_DIR}"

# Stop temporary quick tunnel if running.
docker compose --profile cloudflare-quick stop cloudflared-quick >/dev/null 2>&1 || true
docker compose --profile cloudflare-quick rm -f cloudflared-quick >/dev/null 2>&1 || true

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build mongodb backend cloudflared

echo "Containers:"
docker compose ps backend mongodb cloudflared

echo "Checking local API..."
docker compose exec -T backend python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
echo "Local API is healthy."

if [ -n "${CLOUDFLARE_PUBLIC_URL:-}" ]; then
  echo "Checking public API: ${CLOUDFLARE_PUBLIC_URL}/health"
  for _ in $(seq 1 20); do
    if curl -fsS "${CLOUDFLARE_PUBLIC_URL}/health" >/dev/null; then
      echo "Public API is healthy."
      exit 0
    fi
    sleep 2
  done
  echo "Public API check failed."
  exit 1
fi

exit 0
