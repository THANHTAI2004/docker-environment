#!/bin/bash
# MongoDB Restore Script
# Usage: ./restore.sh <backup_file.tar.gz>

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

if [ -z "$1" ]; then
  echo "❌ Error: Backup file required"
  echo "Usage: ./restore.sh <backup_file.tar.gz>"
  exit 1
fi

BACKUP_FILE="$1"
CONTAINER_NAME="${MONGO_CONTAINER_NAME:-mongodb}"
MONGO_USER="${MONGO_ROOT_USERNAME:-admin}"
MONGO_PASS="${MONGO_ROOT_PASSWORD:-mongopassword}"
TEMP_DIR="/tmp/mongo_restore_$$"

if [ ! -f "$BACKUP_FILE" ]; then
  echo "❌ Error: Backup file not found: $BACKUP_FILE"
  exit 1
fi

echo "🔄 Starting MongoDB restore from: $BACKUP_FILE"

# Extract backup
mkdir -p "$TEMP_DIR"
tar -xzf "$BACKUP_FILE" -C "$TEMP_DIR"

# Find backup directory
BACKUP_DIR=$(find "$TEMP_DIR" -mindepth 1 -maxdepth 1 -type d | head -1)

if [ -z "$BACKUP_DIR" ]; then
  echo "❌ Error: Invalid backup format"
  rm -rf "$TEMP_DIR"
  exit 1
fi

# Copy to container
docker cp "$BACKUP_DIR" "$CONTAINER_NAME:/tmp/restore_data"

# Restore database
docker exec "$CONTAINER_NAME" mongorestore \
  --username "$MONGO_USER" \
  --password "$MONGO_PASS" \
  --authenticationDatabase admin \
  --drop \
  /tmp/restore_data

# Clean up
docker exec "$CONTAINER_NAME" rm -rf /tmp/restore_data
rm -rf "$TEMP_DIR"

echo "✅ Restore completed successfully"
