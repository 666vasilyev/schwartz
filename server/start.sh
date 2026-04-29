#!/usr/bin/env sh
set -e
SERVER_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SERVER_DIR/.." && pwd)"
cd "$ROOT" && alembic upgrade head
cd "$SERVER_DIR" && exec uvicorn app.main:app --host 0.0.0.0 --port 8000
