#!/bin/sh
# ---------------------------------------------------------------------------------------------
# Hackeduler - install AND upgrade with one command. Your data is never deleted.
#
#     ./deploy.sh                                  # install / upgrade with current settings
#     ./deploy.sh --port 9090                      # serve on another port (if 8080 is taken)
#     ./deploy.sh --domain hackeduler.example.com  # use the DNS name that points to this server
#     ./deploy.sh --domain hackeduler.example.com --https files    # HTTPS with company certs in ./certs
#     ./deploy.sh --domain hackeduler.example.com --https auto --email you@example.com  # Let's Encrypt
#     ./deploy.sh --help
#
# Options are saved in .env, so later runs need no options. See docs/NETWORK.md.
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

usage() {
  sed -n '3,16p' "$0" | sed 's/^# \{0,1\}//'
  cat <<'TXT'
Options:
  --port N            host port for the app (plain HTTP)             [HACKEDULER_HTTP_PORT, default 8080]
  --bind ADDRESS      0.0.0.0 = all interfaces, 127.0.0.1 = local only [HACKEDULER_BIND_ADDRESS]
  --domain NAME       DNS name of this server ("" to remove)         [HACKEDULER_DOMAIN]
  --https MODE        off | files | auto | internal                  [HACKEDULER_HTTPS]
  --https-port N      HTTPS port when --https is on (default 443)    [HACKEDULER_HTTPS_PORT]
  --http-port N       HTTP->HTTPS redirect port (default 80)         [HACKEDULER_HTTP_REDIRECT_PORT]
  --email ADDRESS     contact email for Let's Encrypt (--https auto) [HACKEDULER_ACME_EMAIL]
TXT
}

# ---- options (saved to .env further down) ----------------------------------------------------
OPT_KEYS=""
opt() { OPT_KEYS="$OPT_KEYS $1"; eval "OPT_$1=\$2"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --port)        [ $# -ge 2 ] || die "--port needs a value"; opt HACKEDULER_HTTP_PORT "$2"; shift 2;;
    --bind)        [ $# -ge 2 ] || die "--bind needs a value"; opt HACKEDULER_BIND_ADDRESS "$2"; shift 2;;
    --domain)      [ $# -ge 2 ] || die "--domain needs a value"; opt HACKEDULER_DOMAIN "$2"; shift 2;;
    --https)       [ $# -ge 2 ] || die "--https needs a value"; opt HACKEDULER_HTTPS "$2"; shift 2;;
    --https-port)  [ $# -ge 2 ] || die "--https-port needs a value"; opt HACKEDULER_HTTPS_PORT "$2"; shift 2;;
    --http-port)   [ $# -ge 2 ] || die "--http-port needs a value"; opt HACKEDULER_HTTP_REDIRECT_PORT "$2"; shift 2;;
    --email)       [ $# -ge 2 ] || die "--email needs a value"; opt HACKEDULER_ACME_EMAIL "$2"; shift 2;;
    -h|--help)     usage; exit 0;;
    *)             die "Unknown option: $1 (see ./deploy.sh --help)";;
  esac
done
is_port() { case "$1" in ''|*[!0-9]*) return 1;; esac; [ "$1" -ge 1 ] && [ "$1" -le 65535 ]; }

rand() { head -c 48 /dev/urandom | base64 | tr -d '\n/+=' | cut -c1-48; }
setenv() {  # setenv KEY VALUE : replace KEY=... in .env, or append it (quoted if it contains spaces)
  case "$2" in *" "*) line="$1=\"$2\"";; *) line="$1=$2";; esac
  if grep -q "^$1=" .env; then
    awk -v k="$1" -v l="$line" 'index($0, k "=") == 1 {print l; next} {print}' .env > .env.new && mv .env.new .env
  else
    printf '%s\n' "$line" >> .env
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

# ---- 2b. network options: save, validate and derive URLs -------------------------------------
# options are only kept if the deployment gets as far as starting: on any earlier error .env is restored
cp .env .env.prev
KEEP_ENV=0
trap '[ "$KEEP_ENV" = 1 ] || { [ -f .env.prev ] && mv .env.prev .env; }' EXIT
for k in $OPT_KEYS; do eval "setenv $k \"\$OPT_$k\""; done
set -a; . ./.env; set +a

HTTP_PORT="${HACKEDULER_HTTP_PORT:-8080}"
HTTPS_MODE="${HACKEDULER_HTTPS:-off}"
DOMAIN="${HACKEDULER_DOMAIN:-}"
HTTPS_PORT="${HACKEDULER_HTTPS_PORT:-443}"
REDIRECT_PORT="${HACKEDULER_HTTP_REDIRECT_PORT:-80}"
is_port "$HTTP_PORT" || die "Invalid port '$HTTP_PORT'."
case "$HTTPS_MODE" in off|files|auto|internal) ;; *) die "--https must be off, files, auto or internal (got '$HTTPS_MODE').";; esac
case "$DOMAIN" in *[!A-Za-z0-9.-]*) die "Invalid domain name '$DOMAIN' (use the bare name, e.g. hackeduler.example.com - no http:// or port).";; esac

if [ "$HTTPS_MODE" != off ]; then
  [ -n "$DOMAIN" ] || die "HTTPS needs a DNS name: add --domain your.dns.name"
  is_port "$HTTPS_PORT" || die "Invalid HTTPS port '$HTTPS_PORT'."
  is_port "$REDIRECT_PORT" || die "Invalid HTTP redirect port '$REDIRECT_PORT'."
  case "$HTTPS_MODE" in
    files)
      [ -s certs/fullchain.pem ] && [ -s certs/privkey.pem ] || \
        die "Put your certificate in certs/fullchain.pem and the private key in certs/privkey.pem (see certs/README.md)."
      CADDY_TLS="/certs/fullchain.pem /certs/privkey.pem";;
    auto)
      [ -n "${HACKEDULER_ACME_EMAIL:-}" ] || die "--https auto needs --email you@example.com (used by Let's Encrypt)."
      [ "$HTTPS_PORT" = 443 ] && [ "$REDIRECT_PORT" = 80 ] || \
        warn "Let's Encrypt validates on public ports 80/443; custom ports only work if they are forwarded from 80/443."
      CADDY_TLS="$HACKEDULER_ACME_EMAIL";;
    internal)
      CADDY_TLS="internal"
      warn "--https internal uses a self-signed certificate: browsers will show a warning. Use 'files' or 'auto' for real users.";;
  esac
  [ "$HTTPS_PORT" = 443 ] && SUFFIX="" || SUFFIX=":$HTTPS_PORT"
  BASE_URL="https://$DOMAIN$SUFFIX"
  setenv HACKEDULER_CADDY_TLS "$CADDY_TLS"
  setenv HACKEDULER_HTTPS_PORT_SUFFIX "$SUFFIX"
  setenv HACKEDULER_COOKIE_SECURE true
  setenv COMPOSE_PROFILES https
else
  if [ -n "$DOMAIN" ]; then
    [ "$HTTP_PORT" = 80 ] && BASE_URL="http://$DOMAIN" || BASE_URL="http://$DOMAIN:$HTTP_PORT"
  else
    BASE_URL="http://localhost:$HTTP_PORT"
  fi
  setenv COMPOSE_PROFILES ""
  if [ "${HACKEDULER_ENVIRONMENT:-development}" != production ]; then setenv HACKEDULER_COOKIE_SECURE false; fi
fi
setenv HACKEDULER_APP_BASE_URL "$BASE_URL"
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

# ---- 4b. make sure the ports are free (ports already used by Hackeduler itself are fine) -------
listening() {  # is something listening on TCP port $1 on this machine?
  if command -v ss >/dev/null 2>&1; then ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq "[:.]$1\$"
  elif command -v netstat >/dev/null 2>&1; then netstat -an 2>/dev/null | grep -i listen | awk '{print $4}' | grep -Eq "[:.]$1\$"
  elif command -v lsof >/dev/null 2>&1; then lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
  else return 1; fi
}
ours() { docker compose ps --format '{{.Ports}}' 2>/dev/null | grep -Eq "[:.]$1->"; }
free_from() { p=$1; while [ "$p" -le 65535 ]; do listening "$p" || { echo "$p"; return; }; p=$((p + 1)); done; }
check_port() {  # check_port PORT HOW-TO-CHANGE
  if listening "$1" && ! ours "$1"; then
    die "Port $1 is already used by another program on this machine. Free it, or choose another one: $2 $(free_from $(( $1 + 1 )))"
  fi
}
check_port "$HTTP_PORT" "./deploy.sh --port"
if [ "$HTTPS_MODE" != off ]; then
  check_port "$HTTPS_PORT" "./deploy.sh --https-port"
  check_port "$REDIRECT_PORT" "./deploy.sh --http-port"
fi

# ---- 5. build & start -----------------------------------------------------------------------
say "Building and starting Hackeduler"
KEEP_ENV=1; rm -f .env.prev
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
say "Done. Open Hackeduler at:  $BASE_URL"
[ -n "$DOMAIN" ] || say "(Other computers: http://<this-server-ip>:$HTTP_PORT - or map a DNS name with ./deploy.sh --domain <name>)"
[ "$HTTPS_MODE" = off ] || say "(The app is also reachable without HTTPS on port $HTTP_PORT; use --bind 127.0.0.1 to allow HTTPS only.)"
say "Database volume: $VOLUME   Backups: $(pwd)/backups"
