"""Data access layer for LeetCode problem tracking."""

from datetime import datetime, timezone
from uuid import UUID

from loguru import logger

from aegis.db.engine import get_pool

# All recognized patterns for tracking coverage
ALL_PATTERNS = [
    "arrays",
    "hash-table",
    "two-pointers",
    "sliding-window",
    "binary-search",
    "linked-list",
    "trees",
    "graphs",
    "dynamic-programming",
    "backtracking",
    "greedy",
    "heap",
    "stack",
    "queue",
    "trie",
    "bit-manipulation",
    "math",
    "string",
]


class LeetCodeRepository:
    """Repository for the leetcode_problems table."""

    async def upsert_problem(
        self,
        *,
        title: str,
        title_slug: str,
        difficulty: str,
        patterns: list[str],
        url: str | None = None,
        solved: bool = False,
        time_complexity: str | None = None,
        notes: str | None = None,
    ) -> UUID:
        """Insert or update a problem. Returns the problem ID."""
        pool = await get_pool()
        now = datetime.now(timezone.utc)
        row = await pool.fetchrow(
            """
            INSERT INTO leetcode_problems
                (title, title_slug, difficulty, patterns, url, solved,
                 time_complexity, notes, solved_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (title_slug) DO UPDATE SET
                solved = GREATEST(leetcode_problems.solved, EXCLUDED.solved),
                attempts = leetcode_problems.attempts + 1,
                time_complexity = COALESCE(EXCLUDED.time_complexity, leetcode_problems.time_complexity),
                notes = COALESCE(EXCLUDED.notes, leetcode_problems.notes),
                solved_at = CASE
                    WHEN EXCLUDED.solved AND leetcode_problems.solved_at IS NULL
                    THEN EXCLUDED.solved_at
                    ELSE leetcode_problems.solved_at
                END
            RETURNING id
            """,
            title,
            title_slug,
            difficulty,
            patterns,
            url,
            solved,
            time_complexity,
            notes,
            now if solved else None,
        )
        return row["id"]

    async def get_by_slug(self, title_slug: str) -> dict | None:
        pool = await get_pool()
        row = await pool.fetchrow(
            "SELECT * FROM leetcode_problems WHERE title_slug = $1", title_slug
        )
        return dict(row) if row else None

    async def list_solved(self) -> list[dict]:
        pool = await get_pool()
        rows = await pool.fetch(
            "SELECT * FROM leetcode_problems WHERE solved = true ORDER BY solved_at DESC"
        )
        return [dict(r) for r in rows]

    async def list_attempted(self) -> list[dict]:
        pool = await get_pool()
        rows = await pool.fetch(
            "SELECT * FROM leetcode_problems WHERE solved = false ORDER BY created_at DESC"
        )
        return [dict(r) for r in rows]

    async def get_pattern_stats(self) -> dict[str, dict]:
        """Return solved/total counts per pattern."""
        pool = await get_pool()
        rows = await pool.fetch(
            """
            SELECT
                unnest(patterns) AS pattern,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE solved = true) AS solved_count
            FROM leetcode_problems
            GROUP BY pattern
            """
        )
        stats: dict[str, dict] = {}
        for row in rows:
            stats[row["pattern"]] = {
                "total": row["total"],
                "solved": row["solved_count"],
            }
        return stats

    async def get_streak(self) -> int:
        """Calculate current consecutive-day solve streak."""
        pool = await get_pool()
        rows = await pool.fetch(
            """
            SELECT DISTINCT DATE(solved_at AT TIME ZONE 'UTC') AS solve_date
            FROM leetcode_problems
            WHERE solved = true AND solved_at IS NOT NULL
            ORDER BY solve_date DESC
            """
        )
        if not rows:
            return 0

        today = datetime.now(timezone.utc).date()
        streak = 0
        for i, row in enumerate(rows):
            expected = today - __import__("datetime").timedelta(days=i)
            if row["solve_date"] == expected:
                streak += 1
            else:
                break
        return streak

    async def get_all(self) -> list[dict]:
        pool = await get_pool()
        rows = await pool.fetch(
            "SELECT * FROM leetcode_problems ORDER BY created_at DESC"
        )
        return [dict(r) for r in rows]
