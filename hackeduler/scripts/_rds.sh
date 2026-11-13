# Shared by backup-db.sh / restore-db.sh: loads .env and defines pg(), which runs a PostgreSQL client tool
# (psql, pg_dump, pg_restore) in a throw-away container against Amazon RDS. Nothing is installed on the host.
[ -f .env ] || { echo "No .env here - run from the hackeduler folder after ./deploy.sh." >&2; exit 1; }
set -a; . ./.env; set +a
DB_HOST="${HACKEDULER_DB_HOST:?HACKEDULER_DB_HOST is not set in .env}"
DB_PORT="${HACKEDULER_DB_PORT:-5432}"; DB_NAME="${HACKEDULER_DB_NAME:-hackeduler}"; DB_USER="${HACKEDULER_DB_USER:-hackeduler}"
DB_SSLMODE="${HACKEDULER_DB_SSLMODE:-verify-full}"
PG_IMAGE="${HACKEDULER_PG_CLIENT_IMAGE:-postgres:16-alpine}"   # use your RDS major version if it is newer than 16
mkdir -p backups certs
pg() {
  docker run --rm -i --user "$(id -u):$(id -g)" -e PGPASSWORD="${HACKEDULER_DB_PASSWORD:?}" -e PGSSLMODE="$DB_SSLMODE" \
    -e PGSSLROOTCERT="/certs/$(basename "${HACKEDULER_DB_SSLROOTCERT:-/certs/rds-global-bundle.pem}")" -e PGCONNECT_TIMEOUT=10 \
    -v "$(pwd)/certs:/certs:ro" -v "$(pwd)/backups:/backups" "$PG_IMAGE" "$@"
}
