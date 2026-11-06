#!/bin/sh
# Runs inside the "backup" container: dumps the database every INTERVAL_HOURS into /backups
# (= ./backups on the host) and keeps KEEP_DAYS days of automatic backups.
set -u
while true; do
  stamp=$(date +%Y%m%d-%H%M%S)
  target="/backups/auto-$stamp.dump"
  if pg_dump -h db -U "$DB_USER" -d "$DB_NAME" -Fc -f "$target.partial" && [ -s "$target.partial" ]; then
    mv "$target.partial" "$target"
    echo "$(date) backup ok: $target"
  else
    echo "$(date) BACKUP FAILED" >&2
    [ -f "$target.partial" ] && mv "$target.partial" "/backups/failed-$stamp.partial"
  fi
  # retention: only automatic backups older than KEEP_DAYS are pruned; manual and pre-deploy backups are kept
  find /backups -maxdepth 1 -type f -name 'auto-*.dump' -mtime +"$KEEP_DAYS" -exec rm -f {} \;
  sleep $((INTERVAL_HOURS * 3600))
done
