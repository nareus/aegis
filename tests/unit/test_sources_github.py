"""Tests for GitHub source client."""

import respx
from httpx import Response

from aegis.sources.github import GitHubSource


@respx.mock
async def test_github_fetch_success(load_fixture):
    notifications = load_fixture("github_notifications.json")
    events = load_fixture("github_events.json")
    starred = load_fixture("github_starred.json")

    respx.get("https://api.github.com/notifications").mock(
        return_value=Response(200, json=notifications)
    )
    respx.get("https://api.github.com/users/nareus/events").mock(
        return_value=Response(200, json=events)
    )
    respx.get("https://api.github.com/user/starred").mock(
        return_value=Response(200, json=starred)
    )

    source = GitHubSource()
    result = await source.fetch()

    assert result.ok is True
    assert result.source == "github"
    assert len(result.data["notifications"]) == 2
    assert result.data["notifications"][0]["repo"] == "narenarya3/aegis"
    assert len(result.data["events"]) == 2
    assert result.data["events"][0]["type"] == "PushEvent"
    assert len(result.data["starred"]) == 2
    assert result.data["starred"][0]["name"] == "langchain-ai/langgraph"


@respx.mock
async def test_github_fetch_api_error():
    respx.get("https://api.github.com/notifications").mock(
        return_value=Response(401, json={"message": "Bad credentials"})
    )

    source = GitHubSource()
    result = await source.fetch()

    assert result.ok is False
    assert result.source == "github"
    assert result.error is not None
    assert "401" in result.error


@respx.mock
async def test_github_fetch_timeout():
    respx.get("https://api.github.com/notifications").mock(side_effect=TimeoutError())

    source = GitHubSource()
    result = await source.fetch()

    assert result.ok is False
    assert result.source == "github"
