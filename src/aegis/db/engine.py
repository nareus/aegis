"""Async database engine and connection pool management."""

import asyncpg
from loguru import logger
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from aegis.config import settings

_pool: asyncpg.Pool | None = None


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((OSError, asyncpg.PostgresConnectionError)),
    before_sleep=before_sleep_log(logger, "WARNING"),
    reraise=True,
)
async def _create_pool() -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=2,
        max_size=10,
    )


async def get_pool() -> asyncpg.Pool:
    """Get or create the asyncpg connection pool (with retry on cold-start)."""
    global _pool
    if _pool is None:
        _pool = await _create_pool()
        logger.info("Database pool created")
    return _pool


async def close_pool() -> None:
    """Close the connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed")
