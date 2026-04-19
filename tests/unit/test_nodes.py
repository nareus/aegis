"""Tests for individual briefing graph nodes."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from aegis.briefing.nodes import (
    _fetch_source,
    check_fetches,
    route_after_fetches,
    route_after_evaluate,
    degraded_output,
    _parse_json_safe,
)
from aegis.sources.base import SourceResult


# --- route_after_fetches ---

def test_route_prioritize_when_any_ok():
    state = {"raw": {"github": {"data": "ok"}, "hn": None}, "fetch_errors": {"hn": "timeout"}}
    assert route_after_fetches(state) == "prioritize"


def test_route_degraded_when_all_fail():
    state = {"raw": {"github": None, "hn": None}, "fetch_errors": {"github": "err", "hn": "err"}}
    assert route_after_fetches(state) == "degraded_output"


def test_route_degraded_when_raw_empty():
    state = {"raw": {}}
    assert route_after_fetches(state) == "degraded_output"


# --- route_after_evaluate ---

def test_route_persist_when_good_score():
    state = {"quality_score": 0.85, "iterations": 1}
    assert route_after_evaluate(state) == "persist"


def test_route_refine_when_low_score():
    state = {"quality_score": 0.5, "iterations": 1}
    assert route_after_evaluate(state) == "synthesize"


def test_route_persist_when_max_iterations():
    state = {"quality_score": 0.3, "iterations": 2}
    assert route_after_evaluate(state) == "persist"


def test_route_persist_on_first_iteration_good_score():
    state = {"quality_score": 0.7, "iterations": 1}
    assert route_after_evaluate(state) == "persist"


# --- degraded_output ---

async def test_degraded_output_lists_errors():
    state = {
        "fetch_errors": {"github": "401 Unauthorized", "hn": "timeout"},
        "raw": {},
    }
    result = await degraded_output(state)

    assert "Degraded" in result["briefing_markdown"]
    assert "github" in result["briefing_markdown"]
    assert "401 Unauthorized" in result["briefing_markdown"]
    assert result["quality_score"] == 0.0


# --- _fetch_source ---

async def test_fetch_source_success():
    source = MagicMock()
    source.name = "test_source"
    source.fetch = AsyncMock(
        return_value=SourceResult(source="test_source", ok=True, data={"key": "value"})
    )
    state = {"run_id": "abc", "raw": {}, "fetch_errors": {}}

    result = await _fetch_source(state, source)

    assert result["raw"]["test_source"] == {"key": "value"}
    assert "test_source" not in result["fetch_errors"]


async def test_fetch_source_failure():
    source = MagicMock()
    source.name = "test_source"
    source.fetch = AsyncMock(
        return_value=SourceResult(source="test_source", ok=False, error="network error")
    )
    state = {"run_id": "abc", "raw": {}, "fetch_errors": {}}

    result = await _fetch_source(state, source)

    assert result["raw"]["test_source"] is None
    assert result["fetch_errors"]["test_source"] == "network error"


# --- _parse_json_safe ---

def test_parse_json_safe_plain():
    assert _parse_json_safe('{"key": "value"}') == {"key": "value"}


def test_parse_json_safe_fenced():
    text = '```json\n{"key": "value"}\n```'
    assert _parse_json_safe(text) == {"key": "value"}


def test_parse_json_safe_invalid():
    assert _parse_json_safe("not json") == {}
