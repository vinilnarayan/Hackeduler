#!/bin/sh
# ---------------------------------------------------------------------------------------------
# Hackeduler (AWS: EC2 + RDS + SES) - install AND upgrade with one command. Your data is never deleted.
#
#     ./deploy.sh                                  # install / upgrade with current settings
#     ./deploy.sh --port 7090                      # serve on another host port (if 7080 is taken)
#     ./deploy.sh --public-url https://hackeduler.example.com   # an AWS load balancer / proxy terminates HTTPS
#     ./deploy.sh --domain hackeduler.example.com --https files    # built-in HTTPS with company certs in ./certs
#     ./deploy.sh --help
#
# Options are saved in .env, so later runs need no options. See docs/AWS.md.
#
# Every run:
#   1. First run only: creates .env with strong random secrets, then stops so you can enter the RDS details.
#   2. Checks the RDS settings, downloads the RDS CA bundle, and proves the database is reachable.
#   3. Backs up the RDS database into ./backups before changing anything (stops if that fails).
#   4. Builds and starts the new version. Migrations run automatically and only ADD tables/columns.
#   5. Waits until the application is healthy and prints the result.
# This machine is shared with other applications: only the "hackeduler" compose project is touched, and only the
# ports you choose are used (default 7080 / 7443 / 7081).
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
  sed -n '3,19p' "$0" | sed 's/^# \{0,1\}//'
  cat <<'TXT'
Options:
  --port N            host port for the app (plain HTTP)             [HACKEDULER_HTTP_PORT, default 7080]
  --bind ADDRESS      0.0.0.0 = all interfaces, 127.0.0.1 = local only [HACKEDULER_BIND_ADDRESS]
  --public-url URL    address users open when TLS is handled outside this stack (AWS load balancer, host proxy),
                      e.g. https://hackeduler.example.com            [HACKEDULER_PUBLIC_URL]
  --domain NAME       DNS name of this app, for the built-in HTTPS front ("" to remove) [HACKEDULER_DOMAIN]
  --https MODE        off | files | auto | internal                  [HACKEDULER_HTTPS]
  --https-port N      HTTPS port when --https is on (default 7443)   [HACKEDULER_HTTPS_PORT]
  --http-port N       HTTP->HTTPS redirect port (default 7081)       [HACKEDULER_HTTP_REDIRECT_PORT]
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
    --public-url)  [ $# -ge 2 ] || die "--public-url needs a value"; opt HACKEDULER_PUBLIC_URL "$2"; shift 2;;
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
  setenv HACKEDULER_SECRET_KEY "$(rand)"
  setenv HACKEDULER_ENCRYPTION_KEY "$(rand)"
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

HTTP_PORT="${HACKEDULER_HTTP_PORT:-7080}"
HTTPS_MODE="${HACKEDULER_HTTPS:-off}"
DOMAIN="${HACKEDULER_DOMAIN:-}"
HTTPS_PORT="${HACKEDULER_HTTPS_PORT:-7443}"
REDIRECT_PORT="${HACKEDULER_HTTP_REDIRECT_PORT:-7081}"
is_port "$HTTP_PORT" || die "Invalid port '$HTTP_PORT'."

# the database (Amazon RDS) must be described before anything else happens
DB_HOST="${HACKEDULER_DB_HOST:-}"; DB_PORT="${HACKEDULER_DB_PORT:-5432}"; DB_NAME="${HACKEDULER_DB_NAME:-hackeduler}"
DB_USER="${HACKEDULER_DB_USER:-hackeduler}"; DB_PASSWORD="${HACKEDULER_DB_PASSWORD:-}"
DB_SSLMODE="${HACKEDULER_DB_SSLMODE:-verify-full}"; DB_CA="${HACKEDULER_DB_SSLROOTCERT:-/certs/rds-global-bundle.pem}"
if [ -z "$DB_HOST" ] || [ -z "$DB_PASSWORD" ]; then
  [ "$FRESH" = 1 ] && say "Created .env in $(pwd)"
  die "Enter your Amazon RDS details in .env first: HACKEDULER_DB_HOST (RDS endpoint), HACKEDULER_DB_NAME, HACKEDULER_DB_USER and HACKEDULER_DB_PASSWORD (keep the single quotes). Then run ./deploy.sh again. See docs/AWS.md."
fi
is_port "$DB_PORT" || die "Invalid database port '$DB_PORT'."
case "$DB_SSLMODE" in disable|require|verify-ca|verify-full) ;; *) die "HACKEDULER_DB_SSLMODE must be verify-full, verify-ca, require or disable (got '$DB_SSLMODE').";; esac
[ "$DB_SSLMODE" != disable ] || warn "HACKEDULER_DB_SSLMODE=disable: the database connection is NOT encrypted. Use verify-full with RDS."
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
elif [ -n "${HACKEDULER_PUBLIC_URL:-}" ]; then
  # TLS is terminated outside this stack (AWS load balancer, a proxy on this host): users open PUBLIC_URL
  case "$HACKEDULER_PUBLIC_URL" in
    https://*|http://*) ;; *) die "--public-url must start with https:// (or http://), e.g. https://hackeduler.example.com";;
  esac
  BASE_URL="${HACKEDULER_PUBLIC_URL%/}"
  setenv COMPOSE_PROFILES ""
  case "$BASE_URL" in https://*) setenv HACKEDULER_COOKIE_SECURE true;; *) warn "The public URL is not HTTPS: sign-in cookies are marked insecure and SSO providers will refuse it."; setenv HACKEDULER_COOKIE_SECURE false;; esac
else
  if [ -n "$DOMAIN" ]; then
    [ "$HTTP_PORT" = 80 ] && BASE_URL="http://$DOMAIN" || BASE_URL="http://$DOMAIN:$HTTP_PORT"
  else
    BASE_URL="http://localhost:$HTTP_PORT"
  fi
  setenv COMPOSE_PROFILES ""
  if [ "${HACKEDULER_ENVIRONMENT:-production}" = production ]; then
    die "Production needs HTTPS (sign-in cookies are 'secure'). Tell me the address users will open: --public-url https://<name> (an AWS load balancer or proxy terminates TLS), or use the built-in front: --domain <name> --https files|auto|internal. For a throw-away test set HACKEDULER_ENVIRONMENT=development in .env."
  fi
  setenv HACKEDULER_COOKIE_SECURE false
fi
setenv HACKEDULER_APP_BASE_URL "$BASE_URL"
set -a; . ./.env; set +a

# ---- 3. the database: Amazon RDS ----------------------------------------------------------
PG_IMAGE="${HACKEDULER_PG_CLIENT_IMAGE:-postgres:16-alpine}"   # client tools only; use the major version of your RDS instance
mkdir -p certs backups
CA_FILE="certs/$(basename "$DB_CA")"
case "$DB_SSLMODE" in
  verify-ca|verify-full)
    if [ ! -s "$CA_FILE" ]; then
      say "Downloading the Amazon RDS CA bundle into $CA_FILE"
      URL="https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem"
      if command -v curl >/dev/null 2>&1; then curl -fsSL "$URL" -o "$CA_FILE.tmp" || true
      elif command -v wget >/dev/null 2>&1; then wget -q "$URL" -O "$CA_FILE.tmp" || true; fi
      if [ -s "$CA_FILE.tmp" ] && grep -q 'BEGIN CERTIFICATE' "$CA_FILE.tmp"; then mv "$CA_FILE.tmp" "$CA_FILE"; else
        rm -f "$CA_FILE.tmp"
        die "Could not download the RDS CA bundle. Download $URL on a machine that can, copy it to $(pwd)/$CA_FILE, and run ./deploy.sh again."
      fi
    fi
    chmod 644 "$CA_FILE";;
esac
pg() {  # pg <client command...>: run a PostgreSQL client tool against RDS (nothing is installed on this host)
  docker run --rm --user "$(id -u):$(id -g)" -e PGPASSWORD="$DB_PASSWORD" -e PGSSLMODE="$DB_SSLMODE" -e PGSSLROOTCERT="/certs/$(basename "$CA_FILE")" \
    -e PGCONNECT_TIMEOUT=10 -v "$(pwd)/certs:/certs:ro" -v "$(pwd)/backups:/backups" "$PG_IMAGE" "$@"
}
say "Checking the database connection ($DB_HOST:$DB_PORT, database $DB_NAME, user $DB_USER, sslmode $DB_SSLMODE)"
if ! DB_VERSION="$(pg psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -Atc 'show server_version' 2>&1)"; then
  printf '%s\n' "$DB_VERSION" >&2
  die "Cannot connect to the database. Check: the RDS security group allows port $DB_PORT from this EC2 instance's security group, the endpoint / name / user / password in .env, and that the database '$DB_NAME' exists."
fi
say "Connected to PostgreSQL $DB_VERSION"
[ "${DB_VERSION%%.*}" -ge 14 ] 2>/dev/null || warn "PostgreSQL $DB_VERSION is older than 14; Hackeduler is tested on 16."

if [ "$FRESH" = 0 ] && [ "${HACKEDULER_SEED:-none}" = "demo" ]; then
  warn "HACKEDULER_SEED=demo re-creates demo accounts you may have deleted. Use HACKEDULER_SEED=none for real data."
fi

# ---- 4. backup before changing anything -----------------------------------------------------
HAS_DATA="$(pg psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -Atc "select to_regclass('public.alembic_version') is not null" 2>/dev/null | tr -d '\r' || true)"
if [ "$HAS_DATA" = "t" ]; then
  OUT="backups/pre-deploy-$(date +%Y%m%d-%H%M%S).dump"
  say "Backing up the database to $OUT"
  if ! pg pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -Fc -f "/backups/$(basename "$OUT")" || [ ! -s "$OUT" ]; then
    mv "$OUT" "$OUT.failed" 2>/dev/null || true
    die "Backup failed - nothing was changed. (If the message says 'server version mismatch', set HACKEDULER_PG_CLIENT_IMAGE=postgres:<your RDS major version>-alpine in .env.) Fix the problem and run ./deploy.sh again."
  fi
  say "RDS also keeps its own automated backups and snapshots - see docs/AWS.md."
else
  say "The database is empty (first install) - skipping the pre-deploy backup"
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
docker compose up -d --build

# ---- 6. wait for health ---------------------------------------------------------------------
say "Waiting for the application to become healthy (database migrations run now)"
i=0
while :; do
  CID="$(docker compose ps -q backend)"
  [ -n "$CID" ] && [ "$(docker inspect -f '{{.State.Health.Status}}' "$CID" 2>/dev/null)" = "healthy" ] && break
  i=$((i + 1))
  if [ "$i" -gt 60 ]; then
    docker compose logs --tail=80 backend
    die "Backend did not become healthy. Your data is untouched. If needed: ./scripts/restore-db.sh <latest backup in ./backups>, or restore an RDS snapshot."
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
[ -n "$DOMAIN${HACKEDULER_PUBLIC_URL:-}" ] || say "(Other computers: http://<this-server-ip>:$HTTP_PORT - or map a DNS name with ./deploy.sh --public-url https://<name>)"
[ "$HTTPS_MODE" = off ] || say "(The app is also reachable without HTTPS on port $HTTP_PORT; use --bind 127.0.0.1 to allow HTTPS only.)"
say "Database: $DB_HOST   Backups taken before each deploy: $(pwd)/backups"
