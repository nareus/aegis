"""LeetCode source client -- fetches daily challenge via GraphQL API."""

import httpx
from loguru import logger

from aegis.config import settings
from aegis.sources.base import SourceResult

GRAPHQL_URL = "https://leetcode.com/graphql"
TIMEOUT = 15.0

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
            }
        }
    }
}
"""

USER_PROFILE_QUERY = """
query userPublicProfile($username: String!) {
    matchedUser(username: $username) {
        username
        submitStatsGlobal {
            acSubmissionNum {
                difficulty
                count
            }
        }
        userCalendar {
            streak
            totalActiveDays
        }
    }
}
"""


class LeetCodeSource:
    name = "leetcode"

    async def fetch(self) -> SourceResult:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                headers = {
                    "Content-Type": "application/json",
                    "Referer": "https://leetcode.com",
                }
                if settings.leetcode_session:
                    headers["Cookie"] = f"LEETCODE_SESSION={settings.leetcode_session}"

                daily = await _fetch_daily_challenge(client, headers)
                data: dict = {"daily_challenge": daily}

            logger.info(
                "LeetCode fetch OK: daily challenge = {}",
                daily.get("title", "unknown"),
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
        "url": f"https://leetcode.com{challenge['link']}",
    }
