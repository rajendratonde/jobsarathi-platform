#!/usr/bin/env bash
# Every Foundation check, in the order CI will run them (CI platform = decision T3).
# Requires the local PostgreSQL (docker compose) and a populated .env.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-.venv/Scripts/python}"
[ -x "$PY" ] || PY=".venv/bin/python"
set -a; . ./.env; set +a

echo "== lint";               "$PY" -m ruff check libs services tools
echo "== architecture";       "$PY" tools/check_architecture.py
echo "== library tests";      "$PY" -m pytest libs/tests
for s in identity candidate employer job application learning engagement reference; do
  echo "== service tests: $s"; (cd "services/$s" && "../../$PY" -m pytest)
done
echo "== frontend";           (cd frontend && npm test --silent && npm run build --silent)
echo "ALL CHECKS PASSED"
