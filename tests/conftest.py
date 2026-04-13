"""Shared test fixtures."""

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "sample_source_payloads"


@pytest.fixture
def load_fixture():
    """Load a JSON fixture file by name."""

    def _load(name: str) -> dict | list:
        path = FIXTURES_DIR / name
        return json.loads(path.read_text())

    return _load
