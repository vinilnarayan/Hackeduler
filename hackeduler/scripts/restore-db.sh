#!/bin/sh
# Restore a backup made by backup-db.sh (or a dump from the previous local server) into Amazon RDS.
# REPLACES the current database contents. Usage:  ./scripts/restore-db.sh backups/hackeduler-YYYYMMDD-HHMMSS.dump
set -eu
cd "$(dirname "$0")/.."
[ $# -eq 1 ] && [ -f "$1" ] || { echo "Usage: $0 <backup.dump>" >&2; exit 1; }
. ./scripts/_rds.sh
case "$1" in backups/*) FILE="/backups/${1#backups/}";; *) mkdir -p backups; cp "$1" backups/; FILE="/backups/$(basename "$1")";; esac
printf "This will REPLACE all data in database '%s' on %s with %s. Type 'restore' to continue: " "$DB_NAME" "$DB_HOST" "$1"
read -r answer
[ "$answer" = "restore" ] || { echo "Aborted."; exit 1; }
docker compose stop backend worker 2>/dev/null || true
# --no-owner/--no-privileges: the dump may come from a server with different database users
pg pg_restore -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" --clean --if-exists --no-owner --no-privileges "$FILE"
docker compose start backend worker 2>/dev/null || echo "(Start the application with ./deploy.sh)"
echo "Restore complete."
