"""Redis caching wrapper for API responses."""

import json
from typing import Any

import redis.asyncio as aioredis
from loguru import logger

from aegis.config import settings

_client: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Get or create the Redis client."""
    global _client
    if _client is None:
        _client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def cache_get(key: str) -> Any | None:
    """Get a cached value by key. Returns None on miss or error."""
    try:
        r = await get_redis()
        value = await r.get(key)
        if value is not None:
            return json.loads(value)
    except Exception:
        logger.warning("Cache read failed for key={}", key)
    return None


async def cache_set(key: str, value: Any, ttl_seconds: int = 300) -> None:
    """Set a cached value with TTL. Failures are logged but not raised."""
    try:
        r = await get_redis()
        await r.set(key, json.dumps(value, default=str), ex=ttl_seconds)
    except Exception:
        logger.warning("Cache write failed for key={}", key)


async def close_redis() -> None:
    """Close the Redis client."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
