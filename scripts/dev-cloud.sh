#!/bin/sh
set -eu
SWIM_PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SWIM_RUNTIME_PYTHON=${SWIM_PYTHON:-"$SWIM_PROJECT_ROOT/.venv/bin/python"}
export PYTHONPATH="$SWIM_PROJECT_ROOT/services/cloud/src"
cd "$SWIM_PROJECT_ROOT"
case "${1:-serve}" in
  init-db) exec "$SWIM_RUNTIME_PYTHON" -m swimplatform.cli init-db ;;
  test) exec "$SWIM_RUNTIME_PYTHON" -m pytest ;;
  serve) exec "$SWIM_RUNTIME_PYTHON" -m uvicorn swimplatform.main:create_app --factory --host 127.0.0.1 --port "${SWIM_PORT:-8200}" ;;
  *) echo "用法：sh scripts/dev-cloud.sh [init-db|test|serve]" >&2; exit 2 ;;
esac
