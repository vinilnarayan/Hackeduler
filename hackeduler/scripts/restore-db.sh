#!/bin/sh
# Restore a backup made by backup-db.sh. REPLACES the current database contents.
# Usage:  ./scripts/restore-db.sh backups/hackeduler-YYYYMMDD-HHMMSS.dump
set -eu
cd "$(dirname "$0")/.."
[ $# -eq 1 ] && [ -f "$1" ] || { echo "Usage: $0 <backup.dump>" >&2; exit 1; }
[ -f .env ] && . ./.env
DB_USER="${POSTGRES_USER:-hackeduler}"
DB_NAME="${POSTGRES_DB:-hackeduler}"
printf "This will REPLACE all data in database '%s' with %s. Type 'restore' to continue: " "$DB_NAME" "$1"
read -r answer
[ "$answer" = "restore" ] || { echo "Aborted."; exit 1; }
docker compose stop backend worker
docker compose exec -T db pg_restore -U "$DB_USER" -d "$DB_NAME" --clean --if-exists --no-owner < "$1"
docker compose start backend worker
echo "Restore complete."
