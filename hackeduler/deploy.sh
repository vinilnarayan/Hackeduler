#!/bin/sh
# ---------------------------------------------------------------------------------------------
# Hackeduler - install AND upgrade with one command. Your data is never deleted.
#
#     ./deploy.sh
#
# Every run:
#   1. First run only: creates .env with strong random secrets.
#   2. Renames old setting names in .env (ORP_* -> HACKEDULER_*), keeping a copy in .env.bak.
#   3. Finds the database volume holding your data (also from versions before the rename),
#      or creates it on a fresh install. The volume is "external", so Docker Compose never
#      deletes it.
#   4. Backs up the database into ./backups before changing anything (stops if that fails).
#   5. Builds and starts the new version. Migrations run automatically and only ADD
#      tables/columns.
#   6. Waits until the application is healthy and prints the result.
# ---------------------------------------------------------------------------------------------
set -eu
cd "$(dirname "$0")"

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARNING:\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "Docker is not installed."
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 ('docker compose') is required."
docker info >/dev/null 2>&1 || die "Cannot reach the Docker daemon (is it running? do you need sudo?)."

rand() { head -c 48 /dev/urandom | base64 | tr -d '\n/+=' | cut -c1-48; }
setenv() {  # setenv KEY VALUE : replace KEY=... in .env, or append it
  if grep -q "^$1=" .env; then
    awk -v k="$1" -v v="$2" 'BEGIN{FS=OFS="="} $1==k{print k "=" v; next} {print}' .env > .env.new && mv .env.new .env
  else
    printf '%s=%s\n' "$1" "$2" >> .env
  fi
}

# ---- 1. .env --------------------------------------------------------------------------------
FRESH=0
if [ ! -f .env ]; then
  say "First install: creating .env with random secrets"
  cp .env.example .env
  setenv POSTGRES_PASSWORD "$(rand)"
  setenv HACKEDULER_SECRET_KEY "$(rand)"
  setenv HACKEDULER_ENCRYPTION_KEY "$(rand)"
  setenv HACKEDULER_SEED minimal
  FRESH=1
fi

# ---- 2. old setting names -------------------------------------------------------------------
if grep -q '^ORP_' .env; then
  say "Renaming old ORP_* settings to HACKEDULER_* (previous file saved as .env.bak)"
  cp .env .env.bak
  sed 's/^ORP_/HACKEDULER_/' .env.bak > .env
fi
set -a; . ./.env; set +a

# ---- 3. database volume ---------------------------------------------------------------------
vol_exists() { [ -n "$1" ] && docker volume inspect "$1" >/dev/null 2>&1; }
CONFIGURED="${HACKEDULER_DB_VOLUME:-}"
if vol_exists "$CONFIGURED"; then
  VOLUME="$CONFIGURED"
elif [ "$FRESH" = 0 ] && [ -n "$CONFIGURED" ] && [ "$CONFIGURED" != "hackeduler_pgdata" ]; then
  die "Database volume '$CONFIGURED' (HACKEDULER_DB_VOLUME in .env) does not exist. Refusing to start with an empty database. Check 'docker volume ls'."
elif vol_exists hackeduler_pgdata; then
  VOLUME=hackeduler_pgdata
elif vol_exists offsec-resource-planner_pgdata; then
  VOLUME=offsec-resource-planner_pgdata
  say "Found your data from the previous version (volume $VOLUME)"
else
  VOLUME=hackeduler_pgdata
  [ "$FRESH" = 1 ] || warn "No existing database volume found - creating an empty one ($VOLUME)."
  say "Creating database volume: $VOLUME"
  docker volume create "$VOLUME" >/dev/null
fi
[ "$VOLUME" = "$CONFIGURED" ] || setenv HACKEDULER_DB_VOLUME "$VOLUME"
export HACKEDULER_DB_VOLUME="$VOLUME"

if [ "$FRESH" = 0 ] && [ "${HACKEDULER_SEED:-none}" = "demo" ]; then
  warn "HACKEDULER_SEED=demo re-creates demo accounts you may have deleted. Use HACKEDULER_SEED=none for real data."
fi

# ---- 4. backup before changing anything -----------------------------------------------------
mkdir -p backups
DB_CID="$(docker compose ps -q db 2>/dev/null || true)"
if [ -n "$DB_CID" ] && [ "$(docker inspect -f '{{.State.Running}}' "$DB_CID" 2>/dev/null)" = "true" ]; then
  OUT="backups/pre-deploy-$(date +%Y%m%d-%H%M%S).dump"
  say "Backing up the database to $OUT"
  if ! docker compose exec -T db pg_dump -U "${POSTGRES_USER:-hackeduler}" -d "${POSTGRES_DB:-hackeduler}" -Fc > "$OUT" || [ ! -s "$OUT" ]; then
    mv "$OUT" "$OUT.failed" 2>/dev/null || true
    die "Backup failed - nothing was changed. Fix the problem and run ./deploy.sh again."
  fi
else
  say "Database is not running - skipping the pre-deploy backup (automatic daily backups keep running once started)"
fi

# ---- 5. build & start -----------------------------------------------------------------------
say "Building and starting Hackeduler"
docker compose up -d --build --remove-orphans

# ---- 6. wait for health ---------------------------------------------------------------------
say "Waiting for the application to become healthy (database migrations run now)"
i=0
while :; do
  CID="$(docker compose ps -q backend)"
  [ -n "$CID" ] && [ "$(docker inspect -f '{{.State.Health.Status}}' "$CID" 2>/dev/null)" = "healthy" ] && break
  i=$((i + 1))
  if [ "$i" -gt 60 ]; then
    docker compose logs --tail=80 backend
    die "Backend did not become healthy. Your data is untouched. If needed: ./scripts/restore-db.sh <latest backup in ./backups>"
  fi
  sleep 3
done
docker compose ps

# ---- first install: create the first administrator (only when the database has no users) -------
if [ "$(docker compose exec -T backend python -m app.manage count-users 2>/dev/null | tr -d '\r')" = "0" ]; then
  ADMIN_EMAIL="${HACKEDULER_INITIAL_ADMIN_EMAIL:-admin@hackeduler.local}"
  say "Creating the first administrator account (shown once - store the password safely):"
  docker compose exec -T backend python -m app.manage create-admin "$ADMIN_EMAIL"
fi
say "Done. Hackeduler is running on port ${HACKEDULER_HTTP_PORT:-8080}."
say "Database volume: $VOLUME   Backups: $(pwd)/backups"
