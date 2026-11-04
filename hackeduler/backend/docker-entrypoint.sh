#!/bin/sh
set -e
case "$1" in
  api)
    alembic upgrade head
    if [ "${HACKEDULER_SEED:-none}" = "demo" ]; then python -m app.seed; elif [ "${HACKEDULER_SEED:-none}" = "minimal" ]; then python -m app.seed --minimal; fi
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="*" --workers "${HACKEDULER_WEB_WORKERS:-2}"
    ;;
  worker)
    exec python -m app.worker
    ;;
  migrate)
    exec alembic upgrade head
    ;;
  *)
    exec "$@"
    ;;
esac
