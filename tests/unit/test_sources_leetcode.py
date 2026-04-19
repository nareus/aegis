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
    assert result.data["recent_submissions"] == []


@respx.mock
async def test_leetcode_fetch_with_submissions(load_fixture, monkeypatch):
    """When session + username are set, recent submissions are fetched."""
    import aegis.sources.leetcode as lc_module

    monkeypatch.setattr(lc_module.settings, "leetcode_session", "fake-session")
    monkeypatch.setattr(lc_module.settings, "leetcode_username", "testuser")

    daily_response = load_fixture("leetcode_daily.json")
    submissions_response = load_fixture("leetcode_submissions.json")
    two_sum_details = load_fixture("leetcode_problem_two_sum.json")
    coin_change_details = load_fixture("leetcode_problem_coin_change.json")
    islands_details = load_fixture("leetcode_problem_number_of_islands.json")

    # All go to the same endpoint -- respx matches by request body via side_effect
    call_count = 0
    responses = [
        daily_response,
        submissions_response,
        two_sum_details,
        coin_change_details,
        islands_details,
    ]

    def side_effect(request):
        nonlocal call_count
        resp = responses[min(call_count, len(responses) - 1)]
        call_count += 1
        return Response(200, json=resp)

    respx.post("https://leetcode.com/graphql").mock(side_effect=side_effect)

    source = LeetCodeSource()
    result = await source.fetch()

    assert result.ok is True
    assert len(result.data["recent_submissions"]) == 3
    titles = [s["title"] for s in result.data["recent_submissions"]]
    assert "Two Sum" in titles
    assert "Coin Change" in titles
    assert "Number of Islands" in titles


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
