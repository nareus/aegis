"""Tests for the /jobs REST API endpoints."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

# Patch heavy lifespan deps before importing app
import pytest


@pytest.fixture()
def client():
    """TestClient with lifespan startup bypassed."""
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


SAMPLE_JD = "Senior Backend Engineer at Stripe. Requires Python, Go, PostgreSQL. Remote OK."

ADD_JOB_RESULT = {
    "job_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "company": "Stripe",
    "role": "Senior Backend Engineer",
    "fit_score": 0.85,
    "fit_analysis": {"matching_skills": ["python", "golang"], "missing_skills": []},
}

LIST_JOBS_RESULT = [
    {"job_id": "aaaa", "company": "Stripe", "role": "Backend Engineer", "status": "saved", "fit_score": 0.85},
    {"job_id": "bbbb", "company": "Meta", "role": "SWE", "status": "applied", "fit_score": 0.60},
]


@patch("aegis.api.jobs._svc")
def test_add_job_success(mock_svc, client):
    svc = mock_svc.return_value
    svc.add_job = AsyncMock(return_value=ADD_JOB_RESULT)

    resp = client.post("/jobs", json={"text": SAMPLE_JD, "url": "https://linkedin.com/jobs/123"})

    assert resp.status_code == 201
    body = resp.json()
    assert body["company"] == "Stripe"
    assert body["fit_score"] == 0.85
    svc.add_job.assert_called_once_with(SAMPLE_JD, url="https://linkedin.com/jobs/123")


@patch("aegis.api.jobs._svc")
def test_add_job_no_url(mock_svc, client):
    svc = mock_svc.return_value
    svc.add_job = AsyncMock(return_value=ADD_JOB_RESULT)

    resp = client.post("/jobs", json={"text": SAMPLE_JD})

    assert resp.status_code == 201
    svc.add_job.assert_called_once_with(SAMPLE_JD, url=None)


@patch("aegis.api.jobs._svc")
def test_list_jobs_no_filter(mock_svc, client):
    svc = mock_svc.return_value
    svc.list_jobs = AsyncMock(return_value=LIST_JOBS_RESULT)

    resp = client.get("/jobs")

    assert resp.status_code == 200
    assert len(resp.json()) == 2
    svc.list_jobs.assert_called_once_with(status=None)


@patch("aegis.api.jobs._svc")
def test_list_jobs_with_status_filter(mock_svc, client):
    svc = mock_svc.return_value
    svc.list_jobs = AsyncMock(return_value=[LIST_JOBS_RESULT[1]])

    resp = client.get("/jobs?status=applied")

    assert resp.status_code == 200
    svc.list_jobs.assert_called_once_with(status="applied")


@patch("aegis.api.jobs._svc")
def test_get_job_found(mock_svc, client):
    svc = mock_svc.return_value
    svc.get_job = AsyncMock(return_value={"job_id": "aaaa", "company": "Stripe"})

    resp = client.get("/jobs/aaaa")

    assert resp.status_code == 200
    assert resp.json()["company"] == "Stripe"


@patch("aegis.api.jobs._svc")
def test_get_job_not_found(mock_svc, client):
    svc = mock_svc.return_value
    svc.get_job = AsyncMock(return_value=None)

    resp = client.get("/jobs/does-not-exist")

    assert resp.status_code == 404


@patch("aegis.api.jobs._svc")
def test_update_status_success(mock_svc, client):
    svc = mock_svc.return_value
    svc.update_status = AsyncMock(return_value=True)

    resp = client.patch("/jobs/aaaa/status", json={"status": "applied", "notes": "Applied via LinkedIn"})

    assert resp.status_code == 200
    assert resp.json() == {"updated": True}
    svc.update_status.assert_called_once_with("aaaa", "applied", notes="Applied via LinkedIn")


@patch("aegis.api.jobs._svc")
def test_update_status_not_found(mock_svc, client):
    svc = mock_svc.return_value
    svc.update_status = AsyncMock(return_value=False)

    resp = client.patch("/jobs/bad-id/status", json={"status": "rejected"})

    assert resp.status_code == 404


@patch("aegis.api.jobs._svc")
def test_get_follow_ups(mock_svc, client):
    svc = mock_svc.return_value
    svc.get_follow_ups = AsyncMock(return_value=[{"job_id": "aaaa", "company": "Stripe"}])

    resp = client.get("/jobs/follow-ups?stale_days=5")

    assert resp.status_code == 200
    assert len(resp.json()) == 1
    svc.get_follow_ups.assert_called_once_with(5)


@patch("aegis.api.jobs._svc")
def test_get_top_fits(mock_svc, client):
    svc = mock_svc.return_value
    svc.get_top_fits = AsyncMock(return_value=[ADD_JOB_RESULT])

    resp = client.get("/jobs/top-fits?min_score=0.8")

    assert resp.status_code == 200
    svc.get_top_fits.assert_called_once_with(0.8)
