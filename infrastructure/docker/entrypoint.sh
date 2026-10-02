#!/bin/sh
# serve   - run the API (one process per container; scale with containers)
# migrate - apply this service's Alembic migrations with the migration role, then exit
set -eu
case "${1:-serve}" in
  serve)
    exec uvicorn "${SERVICE_PACKAGE}.main:app" --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --no-server-header
    ;;
  migrate)
    exec alembic -c /srv/service/alembic.ini upgrade head
    ;;
  *)
    exec "$@"
    ;;
esac
