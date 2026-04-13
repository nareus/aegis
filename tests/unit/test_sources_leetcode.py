"""Tests for LeetCode source client."""

import respx
from httpx import Response

from aegis.sources.leetcode import LeetCodeSource


@respx.mock
async def test_leetcode_fetch_success(load_fixture):
    daily_response = load_fixture("leetcode_daily.json")

    respx.post("https://leetcode.com/graphql").mock(
        return_value=Response(200, json=daily_response)
    )

    source = LeetCodeSource()
    result = await source.fetch()

    assert result.ok is True
    assert result.source == "leetcode"
    challenge = result.data["daily_challenge"]
    assert challenge["title"] == "Two Sum"
    assert challenge["difficulty"] == "Easy"
    assert "Array" in challenge["tags"]
    assert challenge["url"] == "https://leetcode.com/problems/two-sum/"


@respx.mock
async def test_leetcode_fetch_api_error():
    respx.post("https://leetcode.com/graphql").mock(
        return_value=Response(429, text="Too Many Requests")
    )

    source = LeetCodeSource()
    result = await source.fetch()

    assert result.ok is False
    assert result.source == "leetcode"
    assert "429" in result.error


@respx.mock
async def test_leetcode_fetch_timeout():
    respx.post("https://leetcode.com/graphql").mock(side_effect=TimeoutError())

    source = LeetCodeSource()
    result = await source.fetch()

    assert result.ok is False
    assert result.source == "leetcode"
