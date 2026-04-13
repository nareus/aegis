"""Tests for Hacker News source client."""

import respx
from httpx import Response

from aegis.sources.hn import HackerNewsSource, _filter_by_interest


@respx.mock
async def test_hn_fetch_success(load_fixture):
    top_stories = load_fixture("hn_topstories.json")
    story_40001 = load_fixture("hn_story_40001.json")
    story_40002 = load_fixture("hn_story_40002.json")
    story_40003 = load_fixture("hn_story_40003.json")
    story_40004 = load_fixture("hn_story_40004.json")

    base = "https://hacker-news.firebaseio.com/v0"
    respx.get(f"{base}/topstories.json").mock(
        return_value=Response(200, json=top_stories)
    )
    respx.get(f"{base}/item/40001.json").mock(
        return_value=Response(200, json=story_40001)
    )
    respx.get(f"{base}/item/40002.json").mock(
        return_value=Response(200, json=story_40002)
    )
    respx.get(f"{base}/item/40003.json").mock(
        return_value=Response(200, json=story_40003)
    )
    respx.get(f"{base}/item/40004.json").mock(
        return_value=Response(200, json=story_40004)
    )

    source = HackerNewsSource()
    result = await source.fetch()

    assert result.ok is True
    assert result.source == "hn"
    stories = result.data["stories"]
    # Only stories matching keywords should be returned
    # 40001 matches "distributed systems" + "rust"
    # 40003 matches "llm" + "open source"
    # 40004 matches "kubernetes"
    # 40002 matches nothing
    assert len(stories) == 3
    titles = [s["title"] for s in stories]
    assert "Show HN: My weekend project" not in titles


def test_filter_by_interest_scoring():
    stories = [
        {"title": "Building distributed systems with Rust and Kubernetes", "score": 100},
        {"title": "My cat blog", "score": 500},
        {"title": "New AI LLM open source tool", "score": 200},
    ]
    filtered = _filter_by_interest(stories)
    assert len(filtered) == 2
    # Both matching stories have 3 keyword hits, so tie-break is by score
    titles = {s["title"] for s in filtered}
    assert "My cat blog" not in titles
    assert "Building distributed systems with Rust and Kubernetes" in titles
    assert "New AI LLM open source tool" in titles


@respx.mock
async def test_hn_fetch_api_error():
    base = "https://hacker-news.firebaseio.com/v0"
    respx.get(f"{base}/topstories.json").mock(
        return_value=Response(500, text="Internal Server Error")
    )

    source = HackerNewsSource()
    result = await source.fetch()

    assert result.ok is False
    assert result.source == "hn"
    assert result.error is not None
