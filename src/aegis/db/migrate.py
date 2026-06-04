"""Apply bundled SQL migrations against the configured database.

Migrations ship inside the wheel under aegis._assets.migrations. Each file
is named NNN_<slug>.sql; NNN is the integer version recorded in the
schema_migrations table (created by migration 001).
"""

from __future__ import annotations

import asyncio
import re

import asyncpg
from loguru import logger

from aegis._assets import path as _asset_path
from aegis.config import settings

_VERSION_RE = re.compile(r"^(\d+)_")


def _migration_files() -> list[tuple[int, str, str]]:
    root = _asset_path("migrations")
    entries: list[tuple[int, str, str]] = []
    for entry in root.iterdir():
        name = entry.name
        if not name.endswith(".sql"):
            continue
        match = _VERSION_RE.match(name)
        if not match:
            logger.warning(f"Skipping migration with unparseable name: {name}")
            continue
        version = int(match.group(1))
        entries.append((version, name, entry.read_text(encoding="utf-8")))
    entries.sort(key=lambda x: x[0])
    return entries


async def _applied_versions(conn: asyncpg.Connection) -> set[int]:
    try:
        rows = await conn.fetch("SELECT version FROM schema_migrations")
    except asyncpg.UndefinedTableError:
        return set()
    return {r["version"] for r in rows}


async def run_migrations() -> tuple[int, int]:
    """Apply pending migrations. Returns (newly_applied, total_after)."""
    conn = await asyncpg.connect(settings.database_url)
    try:
        applied = await _applied_versions(conn)
        pending = [
            (v, n, sql) for v, n, sql in _migration_files() if v not in applied
        ]
        if not pending:
            return (0, len(applied))

        for version, name, sql in pending:
            logger.info(f"Applying migration {name}")
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES ($1) "
                    "ON CONFLICT DO NOTHING",
                    version,
                )
        return (len(pending), len(applied) + len(pending))
    finally:
        await conn.close()


def run_migrations_sync() -> tuple[int, int]:
    return asyncio.run(run_migrations())
