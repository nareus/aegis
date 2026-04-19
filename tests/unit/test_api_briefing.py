"""Tests for the /briefing REST API endpoints."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    with (
        patch("aegis.app.get_pool", new_callable=AsyncMock),
        patch("aegis.app.close_pool", new_callable=AsyncMock),
        patch("aegis.app.schedule_briefing"),
        patch("aegis.app.start_scheduler"),
        patch("aegis.app.stop_scheduler"),
    ):
        from aegis.app import create_app
        app = create_app()
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


MOCK_RUN_RESULT = {
    "run_id": "run-123",
    "status": "success",
    "briefing_markdown": "## Action Required\n- Review PR #42",
    "quality_score": 0.88,
    "total_cost_usd": 0.012,
    "total_latency_ms": 3200,
    "sources_ok": ["github", "hn", "leetcode"],
    "sources_failed": [],
}

MOCK_RUN_ROW = {
    "run_id": "run-123",
    "briefing_markdown": "## Action Required\n- Review PR #42",
    "quality_score": 0.88,
    "triggered_at": "2026-04-19T07:00:00",
    "trigger_source": "cron",
}


@patch("aegis.api.briefing._svc")
def test_trigger_run(mock_svc, client):
    svc = mock_svc.return_value
    svc.run = AsyncMock(return_value=MOCK_RUN_RESULT)

    resp = client.post("/briefing/run")

    assert resp.status_code == 202
    body = resp.json()
    assert body["run_id"] == "run-123"
    assert body["status"] == "success"
    assert "Action Required" in body["briefing_markdown"]
    svc.run.assert_called_once_with(trigger_source="api")


@patch("aegis.api.briefing._svc")
def test_trigger_run_custom_source(mock_svc, client):
    svc = mock_svc.return_value
    svc.run = AsyncMock(return_value=MOCK_RUN_RESULT)

    resp = client.post("/briefing/run?trigger_source=mcp")

    svc.run.assert_called_once_with(trigger_source="mcp")


@patch("aegis.api.briefing.BriefingRunRepository")
def test_get_latest_found(MockRepo, client):
    repo = MockRepo.return_value
    repo.get_latest = AsyncMock(return_value=MOCK_RUN_ROW)

    resp = client.get("/briefing/latest")

    assert resp.status_code == 200
    assert resp.json()["run_id"] == "run-123"


@patch("aegis.api.briefing.BriefingRunRepository")
def test_get_latest_not_found(MockRepo, client):
    repo = MockRepo.return_value
    repo.get_latest = AsyncMock(return_value=None)

    resp = client.get("/briefing/latest")

    assert resp.status_code == 404


@patch("aegis.api.briefing.BriefingRunRepository")
def test_get_run_found(MockRepo, client):
    repo = MockRepo.return_value
    repo.get_run = AsyncMock(return_value=MOCK_RUN_ROW)

    resp = client.get("/briefing/runs/run-123")

    assert resp.status_code == 200
    assert resp.json()["run_id"] == "run-123"
    repo.get_run.assert_called_once_with("run-123")


@patch("aegis.api.briefing.BriefingRunRepository")
def test_get_run_not_found(MockRepo, client):
    repo = MockRepo.return_value
    repo.get_run = AsyncMock(return_value=None)

    resp = client.get("/briefing/runs/does-not-exist")

    assert resp.status_code == 404


@patch("aegis.api.briefing.BriefingRunRepository")
def test_list_runs(MockRepo, client):
    repo = MockRepo.return_value
    repo.list_recent = AsyncMock(return_value=[MOCK_RUN_ROW, MOCK_RUN_ROW])

    resp = client.get("/briefing/runs?limit=5")

    assert resp.status_code == 200
    assert len(resp.json()) == 2
    repo.list_recent.assert_called_once_with(5)
