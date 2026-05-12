"""Health check endpoint."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from aegis.db.engine import get_pool

router = APIRouter()


@router.get("/health")
async def health() -> JSONResponse:
    """Liveness check with DB and Redis ping. Returns 503 if any dependency is unhealthy."""
    checks = {"status": "ok", "db": "ok", "redis": "ok"}

    try:
        pool = await get_pool()
        await pool.fetchval("SELECT 1")
    except Exception as e:
        checks["db"] = f"error: {e}"
        checks["status"] = "degraded"

    try:
        import redis.asyncio as aioredis
        from aegis.config import settings

        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
    except Exception as e:
        checks["redis"] = f"error: {e}"
        checks["status"] = "degraded"

    status_code = 200 if checks["status"] == "ok" else 503
    return JSONResponse(content=checks, status_code=status_code)
