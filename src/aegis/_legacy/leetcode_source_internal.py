"""Internal source: reads LeetCode progress from DB for the daily briefing."""

from loguru import logger

from aegis._legacy.leetcode_repository import LeetCodeRepository
from aegis.sources.base import SourceResult


class LeetCodeProgressSource:
    """Reads LeetCode progress data from the internal DB."""

    name = "leetcode_progress"

    def __init__(self) -> None:
        self._repo = LeetCodeRepository()

    async def fetch(self) -> SourceResult:
        try:
            pattern_stats = await self._repo.get_pattern_stats()
            streak = await self._repo.get_streak()
            solved = await self._repo.list_solved()
            attempted = await self._repo.list_attempted()

            # Identify weak patterns (less than 3 solved)
            weak_patterns = []
            for pattern, stats in sorted(pattern_stats.items(), key=lambda x: x[1]["solved"]):
                if stats["solved"] < 3:
                    weak_patterns.append({
                        "pattern": pattern,
                        "solved": stats["solved"],
                        "total": stats["total"],
                    })

            # Difficulty breakdown
            by_difficulty: dict[str, int] = {"Easy": 0, "Medium": 0, "Hard": 0}
            for p in solved:
                d = p.get("difficulty", "")
                if d in by_difficulty:
                    by_difficulty[d] += 1

            data = {
                "total_solved": len(solved),
                "total_attempted": len(solved) + len(attempted),
                "streak_days": streak,
                "weak_patterns": weak_patterns[:5],
                "by_difficulty": by_difficulty,
            }

            logger.info(
                "LeetCode progress: {} solved, {} streak, {} weak patterns",
                len(solved),
                streak,
                len(weak_patterns),
            )
            return SourceResult(source=self.name, ok=True, data=data)

        except Exception as e:
            logger.warning("LeetCode progress source failed: {}", str(e))
            return SourceResult(source=self.name, ok=False, error=str(e))
