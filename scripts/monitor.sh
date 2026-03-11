#!/bin/bash
# Health Monitoring Script
# Checks server health and sends alerts if issues detected

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${ENV_FILE:-$PROJECT_ROOT/.env}"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

BACKEND_HOST_PORT="${BACKEND_HOST_PORT:-8000}"
HEALTH_URL="${HEALTH_URL:-http://localhost:${BACKEND_HOST_PORT}/ready}"
if [ -n "${CLOUDFLARE_PUBLIC_URL:-}" ]; then
  HEALTH_URL="${CLOUDFLARE_PUBLIC_URL%/}/ready"
fi

LOG_FILE="/home/tai/docker-environment/logs/health_monitor.log"
ALERT_EMAIL="admin@example.com"  # Configure this

# Create log directory
mkdir -p "$(dirname "$LOG_FILE")"

# Check health endpoint
check_health() {
  RESPONSE=$(curl -sS --connect-timeout 5 --max-time 10 -o /dev/null -w "%{http_code}" "$HEALTH_URL" || true)
  
  if [ "$RESPONSE" = "200" ]; then
    echo "[$(date)] ✅ Server healthy" >> "$LOG_FILE"
    return 0
  else
    echo "[$(date)] ❌ Server unhealthy - HTTP $RESPONSE" >> "$LOG_FILE"
    return 1
  fi
}

# Check Docker containers
check_containers() {
  CONTAINERS=("wearable-backend" "mongodb")

  # If Cloudflare is configured, cloudflared is required.
  if [ -n "${CLOUDFLARE_PUBLIC_URL:-}" ] || [ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]; then
    CONTAINERS+=("cloudflared")
  fi

  # If quick tunnel is running, monitor it too.
  if docker ps --format '{{.Names}}' | grep -q '^cloudflared-quick$'; then
    CONTAINERS+=("cloudflared-quick")
  fi

  ALL_OK=true
  
  for container in "${CONTAINERS[@]}"; do
    if ! docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
      echo "[$(date)] ❌ Container $container is not running" >> "$LOG_FILE"
      ALL_OK=false
      continue
    fi

    HEALTH_STATUS=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container" 2>/dev/null || true)
    if [ "$HEALTH_STATUS" = "unhealthy" ]; then
      echo "[$(date)] ❌ Container $container is unhealthy" >> "$LOG_FILE"
      ALL_OK=false
    fi
  done
  
  if [ "$ALL_OK" = true ]; then
    return 0
  fi
  return 1
}

# Check disk space
check_disk() {
  USAGE=$(df -h / | awk 'NR==2 {print $5}' | sed 's/%//')
  
  if [ "$USAGE" -gt 80 ]; then
    echo "[$(date)] ⚠️  Disk usage high: ${USAGE}%" >> "$LOG_FILE"
    return 1
  fi
  
  return 0
}

# Main monitoring
echo "[$(date)] Starting health check..." >> "$LOG_FILE"

if ! check_health || ! check_containers || ! check_disk; then
  echo "[$(date)] ⚠️  ALERT: System issues detected" >> "$LOG_FILE"
  
  # Send alert (uncomment and configure)
  # echo "Health monitoring detected issues. Check $LOG_FILE" | mail -s "Server Alert" "$ALERT_EMAIL"
  
  exit 1
fi

echo "[$(date)] All systems operational" >> "$LOG_FILE"
exit 0
