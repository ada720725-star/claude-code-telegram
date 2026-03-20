#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "Error: .env file not found. Run: cp .env.example .env" >&2
    exit 1
fi

export $(grep -v '^\s*#' "$ENV_FILE" | grep -v '^\s*$' | xargs)

exec python3 "${SCRIPT_DIR}/telegram_watcher.py" "$@"
