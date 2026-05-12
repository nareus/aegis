#!/bin/sh
# Entrypoint: run DB migrations then start the requested process.
set -e

run_migrations() {
    echo "[entrypoint] Running database migrations..."
    for f in /app/migrations/*.sql; do
        echo "[entrypoint]   Applying $f"
        psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$f"
    done
    echo "[entrypoint] Migrations done."
}

case "$1" in
  api)
    run_migrations
    echo "[entrypoint] Starting API server on :8000"
    exec uvicorn aegis.app:app --host 0.0.0.0 --port 8000
    ;;
  mcp)
    echo "[entrypoint] Starting MCP server (stdio)"
    exec python -m aegis.mcp_server
    ;;
  migrate)
    run_migrations
    ;;
  *)
    exec "$@"
    ;;
esac
