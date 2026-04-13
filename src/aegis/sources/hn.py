"""Hacker News source client -- fetches top stories filtered by interest keywords."""

import asyncio

import httpx
from loguru import logger

from aegis.sources.base import SourceResult

BASE_URL = "https://hacker-news.firebaseio.com/v0"
TIMEOUT = 15.0
MAX_STORIES = 30
MAX_RETURNED = 15

INTEREST_KEYWORDS = [
    "distributed systems",
    "ai",
    "llm",
    "infrastructure",
    "system design",
    "startup",
    "python",
    "golang",
    "rust",
    "kubernetes",
    "database",
    "open source",
    "engineering",
    "api",
    "mcp",
]


class HackerNewsSource:
    name = "hn"

    async def fetch(self) -> SourceResult:
        try:
            async with httpx.AsyncClient(
                base_url=BASE_URL, timeout=TIMEOUT
            ) as client:
                stories = await _fetch_top_stories(client)

            relevant = _filter_by_interest(stories)
            logger.info(
                "HN fetch OK: {} stories fetched, {} relevant",
                len(stories),
                len(relevant),
            )
            return SourceResult(source=self.name, ok=True, data={"stories": relevant})
        except Exception as e:
            logger.warning("HN fetch failed: {}", str(e))
            return SourceResult(source=self.name, ok=False, error=str(e))


async def _fetch_top_stories(client: httpx.AsyncClient) -> list[dict]:
    """Fetch top story IDs then fetch each story's details concurrently."""
    resp = await client.get("/topstories.json")
    resp.raise_for_status()
    story_ids = resp.json()[:MAX_STORIES]

    tasks = [_fetch_story(client, sid) for sid in story_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    stories = []
    for r in results:
        if isinstance(r, dict) and r.get("title"):
            stories.append(r)
    return stories


async def _fetch_story(client: httpx.AsyncClient, story_id: int) -> dict:
    """Fetch a single story by ID."""
    resp = await client.get(f"/item/{story_id}.json")
    resp.raise_for_status()
    item = resp.json()
    if item is None:
        return {}
    return {
        "id": item.get("id"),
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "score": item.get("score", 0),
        "by": item.get("by", ""),
        "descendants": item.get("descendants", 0),
        "hn_url": f"https://news.ycombinator.com/item?id={item.get('id')}",
    }


def _filter_by_interest(stories: list[dict]) -> list[dict]:
    """Filter and rank stories by relevance to interest keywords."""
    scored = []
    for story in stories:
        title_lower = story.get("title", "").lower()
        matches = sum(1 for kw in INTEREST_KEYWORDS if kw in title_lower)
        if matches > 0:
            story["relevance_score"] = matches
            scored.append(story)

    scored.sort(key=lambda s: (s.get("relevance_score", 0), s.get("score", 0)), reverse=True)
    return scored[:MAX_RETURNED]
