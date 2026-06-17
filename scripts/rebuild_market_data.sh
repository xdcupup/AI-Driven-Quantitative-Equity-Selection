#!/bin/bash
# Back up the current DuckDB file and rebuild market data from an empty database.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PATH="$PROJECT_DIR/.venv"
DB_PATH="$PROJECT_DIR/data/quant.duckdb"
BACKUP_DIR="$PROJECT_DIR/data/backups"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

if [ ! -x "$VENV_PATH/bin/python" ]; then
    echo "Python virtual environment not found: $VENV_PATH"
    exit 2
fi

mkdir -p "$BACKUP_DIR"

if [ -f "$DB_PATH" ]; then
    BACKUP_PATH="$BACKUP_DIR/quant_${TIMESTAMP}.duckdb"
    mv "$DB_PATH" "$BACKUP_PATH"
    echo "Existing database backed up to: $BACKUP_PATH"
fi

cd "$PROJECT_DIR"
set +e
"$VENV_PATH/bin/python" pipeline.py --full-refresh "$@"
EXIT_CODE=$?
set -e

if [ "$EXIT_CODE" -ne 0 ]; then
    echo "Rebuild finished with exit code $EXIT_CODE."
    echo "The previous database remains available in $BACKUP_DIR."
fi

exit "$EXIT_CODE"
