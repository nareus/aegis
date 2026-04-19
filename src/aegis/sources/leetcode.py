"""LeetCode source client -- fetches daily challenge and recent submissions."""

import asyncio

import httpx
from loguru import logger

from aegis.config import settings
from aegis.sources.base import SourceResult

GRAPHQL_URL = "https://leetcode.com/graphql"
TIMEOUT = 15.0
RECENT_SUBMISSIONS_LIMIT = 20

DAILY_CHALLENGE_QUERY = """
query questionOfToday {
    activeDailyCodingChallengeQuestion {
        date
        link
        question {
            questionId
            title
            titleSlug
            difficulty
            topicTags {
                name
                slug
            }
        }
    }
}
"""

RECENT_SUBMISSIONS_QUERY = """
query recentAcSubmissions($username: String!, $limit: Int!) {
    recentAcSubmissionList(username: $username, limit: $limit) {
        id
        title
        titleSlug
        timestamp
    }
}
"""

PROBLEM_DETAILS_QUERY = """
query problemDetails($titleSlug: String!) {
    question(titleSlug: $titleSlug) {
        title
        titleSlug
        difficulty
        topicTags {
            name
            slug
        }
    }
}
"""


class LeetCodeSource:
    name = "leetcode"

    async def fetch(self) -> SourceResult:
        try:
            headers = {
                "Content-Type": "application/json",
                "Referer": "https://leetcode.com",
            }
            if settings.leetcode_session:
                headers["Cookie"] = f"LEETCODE_SESSION={settings.leetcode_session}"

            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                daily_task = asyncio.create_task(
                    _fetch_daily_challenge(client, headers)
                )

                submissions_task = None
                if settings.leetcode_session and settings.leetcode_username:
                    submissions_task = asyncio.create_task(
                        _fetch_recent_submissions(client, headers, settings.leetcode_username)
                    )

                daily = await daily_task
                submissions = await submissions_task if submissions_task else []

            data: dict = {
                "daily_challenge": daily,
                "recent_submissions": submissions,
            }

            logger.info(
                "LeetCode fetch OK: daily={}, submissions={}",
                daily.get("title", "unknown"),
                len(submissions),
            )
            return SourceResult(source=self.name, ok=True, data=data)

        except Exception as e:
            logger.warning("LeetCode fetch failed: {}", str(e))
            return SourceResult(source=self.name, ok=False, error=str(e))


async def _fetch_daily_challenge(
    client: httpx.AsyncClient, headers: dict
) -> dict:
    """Fetch today's daily coding challenge."""
    resp = await client.post(
        GRAPHQL_URL,
        headers=headers,
        json={"query": DAILY_CHALLENGE_QUERY},
    )
    resp.raise_for_status()
    result = resp.json()

    challenge = result["data"]["activeDailyCodingChallengeQuestion"]
    question = challenge["question"]
    return {
        "date": challenge["date"],
        "title": question["title"],
        "title_slug": question["titleSlug"],
        "difficulty": question["difficulty"],
        "tags": [t["name"] for t in question["topicTags"]],
        "tag_slugs": [t["slug"] for t in question["topicTags"]],
        "url": f"https://leetcode.com{challenge['link']}",
    }


async def _fetch_recent_submissions(
    client: httpx.AsyncClient, headers: dict, username: str
) -> list[dict]:
    """Fetch recent accepted submissions, then enrich each with problem details."""
    resp = await client.post(
        GRAPHQL_URL,
        headers=headers,
        json={
            "query": RECENT_SUBMISSIONS_QUERY,
            "variables": {"username": username, "limit": RECENT_SUBMISSIONS_LIMIT},
        },
    )
    resp.raise_for_status()
    result = resp.json()

    raw_submissions = result["data"].get("recentAcSubmissionList") or []
    if not raw_submissions:
        return []

    # Deduplicate by title_slug (only fetch details once per problem)
    seen: set[str] = set()
    unique_slugs = []
    for s in raw_submissions:
        slug = s["titleSlug"]
        if slug not in seen:
            seen.add(slug)
            unique_slugs.append(slug)

    # Fetch problem details concurrently (no auth needed)
    detail_tasks = [
        asyncio.create_task(_fetch_problem_details(client, headers, slug))
        for slug in unique_slugs
    ]
    details_list = await asyncio.gather(*detail_tasks, return_exceptions=True)

    details_map: dict[str, dict] = {}
    for slug, detail in zip(unique_slugs, details_list):
        if isinstance(detail, dict):
            details_map[slug] = detail

    # Merge submission timestamps with problem details
    submissions = []
    for s in raw_submissions:
        slug = s["titleSlug"]
        detail = details_map.get(slug, {})
        submissions.append({
            "title": s["title"],
            "title_slug": slug,
            "timestamp": s["timestamp"],
            "difficulty": detail.get("difficulty", "Unknown"),
            "tags": detail.get("tags", []),
            "tag_slugs": detail.get("tag_slugs", []),
            "url": f"https://leetcode.com/problems/{slug}/",
        })

    return submissions


async def _fetch_problem_details(
    client: httpx.AsyncClient, headers: dict, title_slug: str
) -> dict:
    """Fetch difficulty and tags for a single problem."""
    resp = await client.post(
        GRAPHQL_URL,
        headers=headers,
        json={
            "query": PROBLEM_DETAILS_QUERY,
            "variables": {"titleSlug": title_slug},
        },
    )
    resp.raise_for_status()
    result = resp.json()
    q = result["data"].get("question") or {}
    return {
        "difficulty": q.get("difficulty", "Unknown"),
        "tags": [t["name"] for t in q.get("topicTags", [])],
        "tag_slugs": [t["slug"] for t in q.get("topicTags", [])],
    }
