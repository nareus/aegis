"""Shared helpers for parsing LLM JSON output."""

import json

from loguru import logger


def parse_json(text: str) -> dict:
    """Parse JSON, tolerating ```json fences and surrounding whitespace.

    Returns {} on failure (caller decides what to do with empty payload).
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1])
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM JSON: {}", text[:200])
        return {}
