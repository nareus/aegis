"""GitHub source client -- fetches notifications, events, and starred repos."""

import httpx
from loguru import logger

from aegis.config import settings
from aegis.sources.base import SourceResult

BASE_URL = "https://api.github.com"
TIMEOUT = 15.0


class GitHubSource:
    name = "github"

    def __init__(self) -> None:
        self._headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if settings.github_token:
            self._headers["Authorization"] = f"Bearer {settings.github_token}"

    async def fetch(self) -> SourceResult:
        try:
            async with httpx.AsyncClient(
                base_url=BASE_URL, headers=self._headers, timeout=TIMEOUT
            ) as client:
                notifications, events, starred = await _fetch_all(
                    client, settings.github_username
                )
            data = {
                "notifications": notifications,
                "events": events,
                "starred": starred,
            }
            logger.info(
                "GitHub fetch OK: {} notifications, {} events, {} starred",
                len(notifications),
                len(events),
                len(starred),
            )
            return SourceResult(source=self.name, ok=True, data=data)
        except Exception as e:
            logger.warning("GitHub fetch failed: {}", str(e))
            return SourceResult(source=self.name, ok=False, error=str(e))


async def _fetch_all(
    client: httpx.AsyncClient, username: str
) -> tuple[list[dict], list[dict], list[dict]]:
    """Fetch notifications, recent events, and starred repos concurrently."""
    import asyncio

    notifications_task = asyncio.create_task(_fetch_notifications(client))
    events_task = asyncio.create_task(_fetch_events(client, username))
    starred_task = asyncio.create_task(_fetch_starred(client))

    notifications = await notifications_task
    events = await events_task
    starred = await starred_task

    return notifications, events, starred


async def _fetch_notifications(client: httpx.AsyncClient) -> list[dict]:
    """Fetch unread notifications."""
    resp = await client.get("/notifications", params={"per_page": 20})
    resp.raise_for_status()
    raw = resp.json()
    return [
        {
            "id": n["id"],
            "repo": n["repository"]["full_name"],
            "title": n["subject"]["title"],
            "type": n["subject"]["type"],
            "reason": n["reason"],
            "updated_at": n["updated_at"],
            "unread": n["unread"],
        }
        for n in raw
    ]


async def _fetch_events(client: httpx.AsyncClient, username: str) -> list[dict]:
    """Fetch recent public events for the user."""
    resp = await client.get(f"/users/{username}/events", params={"per_page": 20})
    resp.raise_for_status()
    raw = resp.json()
    return [
        {
            "id": e["id"],
            "type": e["type"],
            "repo": e["repo"]["name"],
            "created_at": e["created_at"],
        }
        for e in raw
    ]


async def _fetch_starred(client: httpx.AsyncClient) -> list[dict]:
    """Fetch recently starred repos (most recent first)."""
    resp = await client.get(
        "/user/starred",
        params={"per_page": 10, "sort": "created", "direction": "desc"},
    )
    resp.raise_for_status()
    raw = resp.json()
    return [
        {
            "name": r["full_name"],
            "description": r.get("description", ""),
            "stars": r["stargazers_count"],
            "language": r.get("language"),
            "url": r["html_url"],
        }
        for r in raw
    ]
