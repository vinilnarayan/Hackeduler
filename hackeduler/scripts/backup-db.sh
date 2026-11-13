#!/bin/sh
# Back up the Hackeduler database (Amazon RDS) to ./backups/hackeduler-<timestamp>.dump (PostgreSQL custom format).
# Usage (from the hackeduler/ folder):  ./scripts/backup-db.sh
# RDS also takes automated backups and snapshots (see docs/AWS.md); this is an extra copy you can move anywhere.
set -eu
cd "$(dirname "$0")/.."
. ./scripts/_rds.sh
NAME="hackeduler-$(date +%Y%m%d-%H%M%S).dump"
pg pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -Fc -f "/backups/$NAME"
[ -s "backups/$NAME" ] || { echo "Backup failed: backups/$NAME is empty" >&2; rm -f "backups/$NAME"; exit 1; }
echo "Backup written to backups/$NAME ($(wc -c < "backups/$NAME") bytes)"
