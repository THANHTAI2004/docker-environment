#!/bin/bash
# MongoDB Backup Script
# Usage: ./backup.sh [backup_name]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${ENV_FILE:-$PROJECT_ROOT/.env}"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

BACKUP_DIR="${BACKUP_DIR:-$PROJECT_ROOT/backups}"
CONTAINER_NAME="${MONGO_CONTAINER_NAME:-mongodb}"
MONGO_USER="${MONGO_ROOT_USERNAME:-admin}"
MONGO_PASS="${MONGO_ROOT_PASSWORD:-mongopassword}"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME=${1:-"backup_$DATE"}

# Create backup directory if not exists
mkdir -p "$BACKUP_DIR"

echo "🔄 Starting MongoDB backup: $BACKUP_NAME"

# Run mongodump inside container
docker exec "$CONTAINER_NAME" mongodump \
  --username "$MONGO_USER" \
  --password "$MONGO_PASS" \
  --authenticationDatabase admin \
  --out "/tmp/$BACKUP_NAME"

# Copy backup from container to host
docker cp "$CONTAINER_NAME:/tmp/$BACKUP_NAME" "$BACKUP_DIR/"

# Clean up container backup
docker exec "$CONTAINER_NAME" rm -rf "/tmp/$BACKUP_NAME"

# Compress backup
cd "$BACKUP_DIR"
tar -czf "${BACKUP_NAME}.tar.gz" "$BACKUP_NAME"
rm -rf "$BACKUP_NAME"

echo "✅ Backup completed: $BACKUP_DIR/${BACKUP_NAME}.tar.gz"

# Keep only last 7 backups
ls -t "$BACKUP_DIR"/*.tar.gz | tail -n +8 | xargs -r rm

echo "📦 Backup size: $(du -h "$BACKUP_DIR/${BACKUP_NAME}.tar.gz" | cut -f1)"
echo "📁 Total backups: $(ls -1 "$BACKUP_DIR"/*.tar.gz 2>/dev/null | wc -l)"
