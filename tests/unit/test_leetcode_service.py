"""Tests for LeetCode service logic -- pattern analysis, suggestions, and sync."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from aegis.leetcode.service import (
    LeetCodeService,
    _identify_weak_patterns,
    _compute_coverage,
    _count_by_difficulty,
    _normalise_patterns,
    PATTERN_COVERAGE_THRESHOLD,
)
from aegis.db.leetcode_repository import ALL_PATTERNS
from aegis.llm.gateway import LLMGateway, LLMResult


# --- Pure logic tests (no DB, no LLM) ---

def test_identify_weak_patterns_empty():
    """All patterns are weak when nothing is solved."""
    weak = _identify_weak_patterns({})
    assert set(weak) == set(ALL_PATTERNS)


def test_identify_weak_patterns_filters_covered():
    stats = {
        "arrays": {"solved": PATTERN_COVERAGE_THRESHOLD, "total": 5},
        "dynamic-programming": {"solved": 1, "total": 2},
        "graphs": {"solved": 0, "total": 0},
    }
    weak = _identify_weak_patterns(stats)
    assert "arrays" not in weak
    assert "dynamic-programming" in weak
    assert "graphs" in weak


def test_identify_weak_patterns_sorted_ascending():
    stats = {
        "graphs": {"solved": 2, "total": 3},
        "dynamic-programming": {"solved": 0, "total": 0},
        "arrays": {"solved": 1, "total": 2},
    }
    weak = _identify_weak_patterns(stats)
    # dynamic-programming (0) should come before arrays (1) before graphs (2)
    dp_idx = weak.index("dynamic-programming")
    arrays_idx = weak.index("arrays")
    graphs_idx = weak.index("graphs")
    assert dp_idx < arrays_idx < graphs_idx


def test_compute_coverage_includes_all_patterns():
    coverage = _compute_coverage({})
    assert set(coverage.keys()) == set(ALL_PATTERNS)
    for pattern, data in coverage.items():
        assert data["solved"] == 0
        assert data["covered"] is False


def test_compute_coverage_marks_covered():
    stats = {"arrays": {"solved": PATTERN_COVERAGE_THRESHOLD, "total": 5}}
    coverage = _compute_coverage(stats)
    assert coverage["arrays"]["covered"] is True
    assert coverage["dynamic-programming"]["covered"] is False


def test_count_by_difficulty():
    problems = [
        {"difficulty": "Easy"},
        {"difficulty": "Easy"},
        {"difficulty": "Medium"},
        {"difficulty": "Hard"},
        {"difficulty": "Medium"},
    ]
    counts = _count_by_difficulty(problems)
    assert counts == {"Easy": 2, "Medium": 2, "Hard": 1}


def test_count_by_difficulty_empty():
    assert _count_by_difficulty([]) == {"Easy": 0, "Medium": 0, "Hard": 0}


# --- Service tests with mocked dependencies ---

SUGGESTION_RESPONSE = json.dumps({
    "title_slug": "coin-change",
    "title": "Coin Change",
    "difficulty": "Medium",
    "patterns": ["dynamic-programming"],
    "reason": "Most common DP interview problem, you have 0 DP problems solved.",
    "url": "https://leetcode.com/problems/coin-change/",
})


@patch.object(LeetCodeService, "_get_gateway")
@patch("aegis.leetcode.service.LeetCodeRepository")
async def test_suggest_next_returns_parsed_json(mock_repo_cls, mock_get_gateway):
    mock_repo = MagicMock()
    mock_repo.get_pattern_stats = AsyncMock(return_value={})
    mock_repo_cls.return_value = mock_repo

    mock_gateway = MagicMock(spec=LLMGateway)
    mock_gateway.call = AsyncMock(
        return_value=LLMResult(
            text=SUGGESTION_RESPONSE,
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.001,
            model="test",
        )
    )
    mock_get_gateway.return_value = mock_gateway

    service = LeetCodeService()
    result = await service.suggest_next()

    assert result["title"] == "Coin Change"
    assert result["difficulty"] == "Medium"
    assert "dynamic-programming" in result["patterns"]


@patch.object(LeetCodeService, "_get_gateway")
@patch("aegis.leetcode.service.LeetCodeRepository")
async def test_suggest_next_handles_bad_json(mock_repo_cls, mock_get_gateway):
    mock_repo = MagicMock()
    mock_repo.get_pattern_stats = AsyncMock(return_value={})
    mock_repo_cls.return_value = mock_repo

    mock_gateway = MagicMock(spec=LLMGateway)
    mock_gateway.call = AsyncMock(
        return_value=LLMResult(
            text="not valid json",
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.0,
            model="test",
        )
    )
    mock_get_gateway.return_value = mock_gateway

    service = LeetCodeService()
    result = await service.suggest_next()

    # Should not raise, returns error dict
    assert "error" in result or "reason" in result


# --- Normalise patterns ---

def test_normalise_patterns_known_slugs():
    tags = ["dynamic-programming", "array", "hash-table"]
    result = _normalise_patterns(tags)
    assert "dynamic-programming" in result
    assert "arrays" in result
    assert "hash-table" in result


def test_normalise_patterns_display_names():
    tags = ["Dynamic Programming", "Array", "Graph"]
    result = _normalise_patterns(tags)
    assert "dynamic-programming" in result
    assert "arrays" in result
    assert "graphs" in result


def test_normalise_patterns_unknown_tags_ignored():
    tags = ["concurrency", "unknown-thing", "array"]
    result = _normalise_patterns(tags)
    assert "arrays" in result
    # unknown tags dropped
    assert "concurrency" not in result
    assert "unknown-thing" not in result


def test_normalise_patterns_defaults_to_arrays_when_empty():
    result = _normalise_patterns([])
    assert result == ["arrays"]


# --- Sync from source data ---

@patch("aegis.leetcode.service.LeetCodeRepository")
async def test_sync_from_source_data(mock_repo_cls):
    mock_repo = MagicMock()
    mock_repo.upsert_problem = AsyncMock(return_value="some-uuid")
    mock_repo_cls.return_value = mock_repo

    source_data = {
        "recent_submissions": [
            {
                "title": "Two Sum",
                "title_slug": "two-sum",
                "difficulty": "Easy",
                "tags": ["Array", "Hash Table"],
                "tag_slugs": ["array", "hash-table"],
                "url": "https://leetcode.com/problems/two-sum/",
            },
            {
                "title": "Coin Change",
                "title_slug": "coin-change",
                "difficulty": "Medium",
                "tags": ["Dynamic Programming"],
                "tag_slugs": ["dynamic-programming"],
                "url": "https://leetcode.com/problems/coin-change/",
            },
        ]
    }

    service = LeetCodeService()
    result = await service.sync_from_source_data(source_data)

    assert result["synced"] == 2
    assert result["skipped"] == 0
    assert mock_repo.upsert_problem.call_count == 2


@patch("aegis.leetcode.service.LeetCodeRepository")
async def test_sync_from_source_data_empty(mock_repo_cls):
    mock_repo = MagicMock()
    mock_repo_cls.return_value = mock_repo

    result = await LeetCodeService().sync_from_source_data({})

    assert result == {"synced": 0, "skipped": 0}
    mock_repo.upsert_problem.assert_not_called()
