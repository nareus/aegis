#!/bin/sh
# Entrypoint: run DB migrations then start the requested process.
set -e

run_migrations() {
    echo "[entrypoint] Running database migrations..."
    for f in /app/migrations/*.sql; do
        echo "[entrypoint]   Applying $f"
        psql "$DATABASE_URL" -f "$f" 2>/dev/null || true
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
  worker)
    run_migrations
    echo "[entrypoint] Starting scheduler worker"
    exec python -m aegis.scheduler.worker
    ;;
  migrate)
    run_migrations
    ;;
  *)
    exec "$@"
    ;;
esac
