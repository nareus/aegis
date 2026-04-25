"""One-time bulk import of all accepted LeetCode submissions into Aegis.

Usage:
    uv run python scripts/import_leetcode.py

Requires LEETCODE_SESSION and LEETCODE_USERNAME in .env.
Safe to run multiple times -- uses upsert so no duplicates.
"""

import asyncio
import sys

import httpx
from loguru import logger

GRAPHQL_URL = "https://leetcode.com/graphql"
PAGE_SIZE = 20  # LeetCode max per request

AC_SUBMISSIONS_QUERY = """
query acSubmissions($username: String!, $limit: Int!, $offset: Int!) {
    recentAcSubmissionList(username: $username, limit: $limit) {
        id
        title
        titleSlug
        timestamp
    }
}
"""

# LeetCode doesn't support offset on recentAcSubmissionList,
# so we use the full submission list with status filter instead
ALL_SUBMISSIONS_QUERY = """
query allSubmissions($offset: Int!, $limit: Int!) {
    submissionList(offset: $offset, limit: $limit, status: AC) {
        lastKey
        hasNext
        submissions {
            id
            title
            titleSlug
            statusDisplay
            timestamp
        }
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


async def fetch_all_ac_submissions(client: httpx.AsyncClient, headers: dict) -> list[dict]:
    """Fetch all accepted submissions via paginated submissionList query."""
    submissions = []
    offset = 0

    logger.info("Fetching all accepted submissions from LeetCode...")

    while True:
        resp = await client.post(
            GRAPHQL_URL,
            headers=headers,
            json={
                "query": ALL_SUBMISSIONS_QUERY,
                "variables": {"offset": offset, "limit": PAGE_SIZE},
            },
        )
        resp.raise_for_status()
        data = resp.json()

        page = data.get("data", {}).get("submissionList", {})
        batch = page.get("submissions") or []

        if not batch:
            break

        submissions.extend(batch)
        logger.info("  Fetched {} submissions so far...", len(submissions))

        if not page.get("hasNext"):
            break

        offset += PAGE_SIZE
        await asyncio.sleep(0.5)  # be polite to LeetCode's API

    logger.info("Total accepted submissions fetched: {}", len(submissions))
    return submissions


async def fetch_problem_details(
    client: httpx.AsyncClient, headers: dict, title_slug: str
) -> dict:
    resp = await client.post(
        GRAPHQL_URL,
        headers=headers,
        json={
            "query": PROBLEM_DETAILS_QUERY,
            "variables": {"titleSlug": title_slug},
        },
    )
    resp.raise_for_status()
    q = resp.json().get("data", {}).get("question") or {}
    return {
        "difficulty": q.get("difficulty", "Unknown"),
        "tags": [t["name"] for t in q.get("topicTags", [])],
        "tag_slugs": [t["slug"] for t in q.get("topicTags", [])],
    }


async def main():
    # Load settings
    sys.path.insert(0, "src")
    from aegis.config import settings
    from aegis.db.engine import get_pool, close_pool
    from aegis._legacy.leetcode.service import LeetCodeService

    if not settings.leetcode_session:
        logger.error("LEETCODE_SESSION is not set in .env")
        sys.exit(1)
    if not settings.leetcode_username:
        logger.error("LEETCODE_USERNAME is not set in .env")
        sys.exit(1)

    headers = {
        "Content-Type": "application/json",
        "Referer": "https://leetcode.com",
        "Cookie": f"LEETCODE_SESSION={settings.leetcode_session}",
        "User-Agent": "Mozilla/5.0",
    }

    await get_pool()
    svc = LeetCodeService()

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1: fetch all AC submissions
        submissions = await fetch_all_ac_submissions(client, headers)

        if not submissions:
            logger.warning("No accepted submissions found. Check your LEETCODE_SESSION.")
            await close_pool()
            return

        # Step 2: deduplicate by title_slug
        seen: set[str] = set()
        unique: list[dict] = []
        for s in submissions:
            slug = s.get("titleSlug", "")
            if slug and slug not in seen:
                seen.add(slug)
                unique.append(s)

        logger.info("Unique problems to import: {}", len(unique))

        # Step 3: fetch details and sync in batches
        synced = 0
        failed = 0

        for i, sub in enumerate(unique, 1):
            slug = sub["titleSlug"]
            title = sub["title"]

            try:
                details = await fetch_problem_details(client, headers, slug)

                source_data = {
                    "recent_submissions": [{
                        "title": title,
                        "title_slug": slug,
                        "difficulty": details["difficulty"],
                        "tag_slugs": details["tag_slugs"],
                        "tags": details["tags"],
                        "url": f"https://leetcode.com/problems/{slug}/",
                    }]
                }
                result = await svc.sync_from_source_data(source_data)
                synced += result["synced"]

                if i % 10 == 0:
                    logger.info("  Progress: {}/{}", i, len(unique))

                await asyncio.sleep(0.3)  # avoid rate limiting

            except Exception as e:
                logger.warning("  Failed to import {}: {}", slug, e)
                failed += 1

    await close_pool()

    logger.info("")
    logger.info("Import complete!")
    logger.info("  Synced:  {}", synced)
    logger.info("  Failed:  {}", failed)
    logger.info("  Total unique problems: {}", len(unique))
    logger.info("")
    logger.info("Run 'make api' and check http://localhost:8000/docs to verify.")


if __name__ == "__main__":
    asyncio.run(main())
