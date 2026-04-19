"""LeetCode service -- progress tracking and next-problem suggestions."""

import json

from loguru import logger

from aegis.db.leetcode_repository import LeetCodeRepository, ALL_PATTERNS
from aegis.llm.gateway import LLMGateway

# Minimum solved count per pattern before it's considered "covered"
PATTERN_COVERAGE_THRESHOLD = 3

SUGGEST_SYSTEM = """\
You are a LeetCode coach. Given a candidate's pattern coverage stats, \
suggest the single best next problem to practice.

Prioritize patterns that are:
1. Commonly asked in backend/AI engineering interviews
2. Under-practiced (low solved count relative to total)
3. Foundational (arrays, dynamic-programming, graphs before advanced topics)

Output a JSON object:
{
  "title_slug": "problem-title-slug",
  "title": "Problem Title",
  "difficulty": "Easy" | "Medium" | "Hard",
  "patterns": ["pattern1", "pattern2"],
  "reason": "why this problem is the best next step",
  "url": "https://leetcode.com/problems/problem-title-slug/"
}

Return ONLY valid JSON, no markdown fences."""


class LeetCodeService:
    """High-level service for LeetCode progress tracking."""

    def __init__(self, gateway: LLMGateway | None = None) -> None:
        self._repo = LeetCodeRepository()
        self._gateway = gateway

    def _get_gateway(self) -> LLMGateway:
        if self._gateway is None:
            self._gateway = LLMGateway()
        return self._gateway

    async def log_problem(
        self,
        *,
        title: str,
        title_slug: str,
        difficulty: str,
        patterns: list[str],
        solved: bool = True,
        url: str | None = None,
        time_complexity: str | None = None,
        notes: str | None = None,
    ) -> dict:
        """Log a solved or attempted problem. Returns the saved record."""
        problem_id = await self._repo.upsert_problem(
            title=title,
            title_slug=title_slug,
            difficulty=difficulty,
            patterns=patterns,
            url=url or f"https://leetcode.com/problems/{title_slug}/",
            solved=solved,
            time_complexity=time_complexity,
            notes=notes,
        )
        logger.info(
            "Logged problem: {} ({}) -- solved: {}",
            title,
            difficulty,
            solved,
        )
        return {"id": str(problem_id), "title": title, "solved": solved}

    async def get_progress(self) -> dict:
        """Return a full progress summary: per-pattern stats, weak areas, streak."""
        pattern_stats = await self._repo.get_pattern_stats()
        streak = await self._repo.get_streak()
        solved_list = await self._repo.list_solved()

        weak_patterns = _identify_weak_patterns(pattern_stats)
        coverage = _compute_coverage(pattern_stats)

        return {
            "total_solved": len(solved_list),
            "streak_days": streak,
            "pattern_coverage": coverage,
            "weak_patterns": weak_patterns,
            "by_difficulty": _count_by_difficulty(solved_list),
        }

    async def suggest_next(self) -> dict:
        """Suggest the next best problem to practice based on gaps."""
        pattern_stats = await self._repo.get_pattern_stats()
        weak_patterns = _identify_weak_patterns(pattern_stats)
        coverage_summary = _format_coverage_for_prompt(pattern_stats)

        gateway = self._get_gateway()
        result = await gateway.call(
            system=SUGGEST_SYSTEM,
            user=(
                f"Pattern coverage:\n{coverage_summary}\n\n"
                f"Weakest patterns: {', '.join(weak_patterns[:5])}"
            ),
            max_tokens=512,
        )

        try:
            cleaned = result.text.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                cleaned = "\n".join(lines[1:-1])
            suggestion = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("Failed to parse suggestion JSON: {}", result.text[:200])
            suggestion = {"reason": "Unable to generate suggestion", "error": result.text}

        logger.info("Next problem suggestion: {}", suggestion.get("title", "unknown"))
        return suggestion

    async def get_weak_patterns(self) -> list[str]:
        """Return patterns with fewer than threshold solved problems."""
        pattern_stats = await self._repo.get_pattern_stats()
        return _identify_weak_patterns(pattern_stats)

    async def sync_from_source_data(self, source_data: dict) -> dict:
        """Sync recent accepted submissions from LeetCode source fetch data.

        Args:
            source_data: The `data` field from a LeetCodeSource SourceResult.

        Returns:
            Dict with counts of synced and skipped problems.
        """
        submissions: list[dict] = source_data.get("recent_submissions", [])
        if not submissions:
            return {"synced": 0, "skipped": 0}

        synced = 0
        skipped = 0

        for sub in submissions:
            title_slug = sub.get("title_slug", "")
            title = sub.get("title", "")
            difficulty = sub.get("difficulty", "Unknown")
            tag_slugs = sub.get("tag_slugs", [])
            tags = sub.get("tags", [])
            url = sub.get("url", f"https://leetcode.com/problems/{title_slug}/")

            if not title_slug or not title:
                skipped += 1
                continue

            # Normalise tags to our pattern slugs (LeetCode uses camelCase slugs)
            patterns = _normalise_patterns(tag_slugs or tags)

            await self._repo.upsert_problem(
                title=title,
                title_slug=title_slug,
                difficulty=difficulty,
                patterns=patterns,
                url=url,
                solved=True,
            )
            synced += 1

        logger.info(
            "LeetCode sync: {} problems synced, {} skipped",
            synced,
            skipped,
        )
        return {"synced": synced, "skipped": skipped}


def _identify_weak_patterns(pattern_stats: dict[str, dict]) -> list[str]:
    """Return patterns under the coverage threshold, sorted by solved count ascending."""
    weak = []
    for pattern in ALL_PATTERNS:
        stats = pattern_stats.get(pattern, {"solved": 0, "total": 0})
        if stats["solved"] < PATTERN_COVERAGE_THRESHOLD:
            weak.append((pattern, stats["solved"]))
    weak.sort(key=lambda x: x[1])
    return [p for p, _ in weak]


def _compute_coverage(pattern_stats: dict[str, dict]) -> dict[str, dict]:
    """Build a full coverage dict including patterns with zero solved."""
    coverage = {}
    for pattern in ALL_PATTERNS:
        stats = pattern_stats.get(pattern, {"solved": 0, "total": 0})
        coverage[pattern] = {
            "solved": stats["solved"],
            "total": stats["total"],
            "covered": stats["solved"] >= PATTERN_COVERAGE_THRESHOLD,
        }
    return coverage


def _count_by_difficulty(solved_list: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {"Easy": 0, "Medium": 0, "Hard": 0}
    for p in solved_list:
        diff = p.get("difficulty", "")
        if diff in counts:
            counts[diff] += 1
    return counts


def _format_coverage_for_prompt(pattern_stats: dict[str, dict]) -> str:
    lines = []
    for pattern in ALL_PATTERNS:
        stats = pattern_stats.get(pattern, {"solved": 0, "total": 0})
        lines.append(f"  {pattern}: {stats['solved']} solved / {stats['total']} attempted")
    return "\n".join(lines)


def _normalise_patterns(raw_tags: list[str]) -> list[str]:
    """Convert LeetCode tag names/slugs to our internal pattern slugs.

    LeetCode returns tags like 'Dynamic Programming' or 'dynamic-programming'.
    We normalise to lowercase hyphenated slugs and keep only known patterns.
    """
    normalised = []
    for tag in raw_tags:
        slug = tag.lower().replace(" ", "-")
        # Map common LeetCode tag variants to our slugs
        slug = _TAG_MAP.get(slug, slug)
        if slug in ALL_PATTERNS:
            normalised.append(slug)
    return normalised or ["arrays"]  # default if no known patterns found


# Map LeetCode tag slugs to our internal pattern names where they differ
_TAG_MAP: dict[str, str] = {
    "dynamic-programming": "dynamic-programming",
    "hash-table": "hash-table",
    "two-pointers": "two-pointers",
    "sliding-window": "sliding-window",
    "binary-search": "binary-search",
    "linked-list": "linked-list",
    "tree": "trees",
    "binary-tree": "trees",
    "graph": "graphs",
    "backtracking": "backtracking",
    "greedy": "greedy",
    "heap-priority-queue": "heap",
    "stack": "stack",
    "queue": "queue",
    "trie": "trie",
    "bit-manipulation": "bit-manipulation",
    "math": "math",
    "string": "string",
    "array": "arrays",
}
