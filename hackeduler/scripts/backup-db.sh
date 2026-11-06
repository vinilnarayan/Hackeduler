#!/bin/sh
# Back up the Hackeduler database to ./backups/hackeduler-<timestamp>.dump (PostgreSQL custom format).
# Usage (from the hackeduler/ folder, while the stack is running):  ./scripts/backup-db.sh
set -eu
cd "$(dirname "$0")/.."
[ -f .env ] && . ./.env
DB_USER="${POSTGRES_USER:-hackeduler}"
DB_NAME="${POSTGRES_DB:-hackeduler}"
mkdir -p backups
OUT="backups/hackeduler-$(date +%Y%m%d-%H%M%S).dump"
docker compose exec -T db pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc > "$OUT"
[ -s "$OUT" ] || { echo "Backup failed: $OUT is empty" >&2; rm -f "$OUT"; exit 1; }
echo "Backup written to $OUT ($(wc -c < "$OUT") bytes)"
