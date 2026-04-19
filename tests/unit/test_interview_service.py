"""Tests for InterviewService."""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from aegis.interview.service import InterviewService, _parse_json, _format_sessions_for_prompt
from aegis.llm.gateway import LLMGateway, LLMResult


SESSION_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

QUESTION_TEXT = "Design a distributed rate limiter for an API gateway. Walk me through your design."

EVALUATE_RESPONSE = json.dumps({
    "score": 0.78,
    "strengths": ["Clear token bucket explanation", "Considered Redis for shared state"],
    "gaps": ["Did not discuss consistency guarantees", "No mention of circuit breaker"],
    "weak_areas": ["distributed-systems", "fault-tolerance"],
    "suggested_improvements": "Discuss CAP theorem trade-offs and how you'd handle Redis failure.",
    "model_answer_hint": "Token bucket in Redis, sliding window log, fallback to local counter.",
})

READINESS_RESPONSE = json.dumps({
    "readiness_level": "developing",
    "summary": "Candidate shows solid fundamentals but needs more depth on distributed systems.",
    "key_gaps": ["distributed-systems", "fault-tolerance", "system-design breadth"],
    "recommended_next": "Practice one system design question per day focusing on distributed topics.",
})


def _llm_mock(text: str) -> LLMGateway:
    gw = MagicMock(spec=LLMGateway)
    gw.call = AsyncMock(
        return_value=LLMResult(text=text, input_tokens=200, output_tokens=100, cost_usd=0.002, model="test")
    )
    return gw


# --- mock_system_design ---

@patch("aegis.interview.service.InterviewRepository")
async def test_mock_system_design_returns_question(MockRepo):
    repo = MockRepo.return_value
    repo.create_session = AsyncMock(return_value=SESSION_ID)

    svc = InterviewService(gateway=_llm_mock(QUESTION_TEXT))
    result = await svc.mock_system_design(company="Stripe", topic="rate limiting")

    assert result["question"] == QUESTION_TEXT
    assert result["session_id"] == str(SESSION_ID)
    assert result["session_type"] == "system-design"
    assert result["company"] == "Stripe"
    repo.create_session.assert_called_once()


@patch("aegis.interview.service.InterviewRepository")
async def test_mock_system_design_no_company(MockRepo):
    repo = MockRepo.return_value
    repo.create_session = AsyncMock(return_value=SESSION_ID)

    svc = InterviewService(gateway=_llm_mock(QUESTION_TEXT))
    result = await svc.mock_system_design()

    assert result["company"] is None


# --- mock_behavioral ---

@patch("aegis.interview.service.InterviewRepository")
async def test_mock_behavioral_returns_question(MockRepo):
    repo = MockRepo.return_value
    repo.create_session = AsyncMock(return_value=SESSION_ID)

    behavioral_q = "Tell me about a time you had to resolve a technical disagreement with a teammate."
    svc = InterviewService(gateway=_llm_mock(behavioral_q))
    result = await svc.mock_behavioral(company="Google")

    assert result["session_type"] == "behavioral"
    assert result["question"] == behavioral_q
    assert result["company"] == "Google"


# --- evaluate_answer ---

@patch("aegis.interview.service.InterviewRepository")
async def test_evaluate_answer_parses_and_persists(MockRepo):
    repo = MockRepo.return_value
    repo.get_session = AsyncMock(return_value={
        "id": SESSION_ID,
        "question": QUESTION_TEXT,
        "session_type": "system-design",
    })
    repo.save_answer = AsyncMock()

    svc = InterviewService(gateway=_llm_mock(EVALUATE_RESPONSE))
    result = await svc.evaluate_answer(str(SESSION_ID), "I would use Redis with token bucket...")

    assert result["score"] == 0.78
    assert "distributed-systems" in result["weak_areas"]
    assert len(result["strengths"]) > 0
    repo.save_answer.assert_called_once()
    call_kwargs = repo.save_answer.call_args.kwargs
    assert call_kwargs["score"] == 0.78
    assert "distributed-systems" in call_kwargs["weak_areas"]


@patch("aegis.interview.service.InterviewRepository")
async def test_evaluate_answer_session_not_found(MockRepo):
    repo = MockRepo.return_value
    repo.get_session = AsyncMock(return_value=None)

    svc = InterviewService(gateway=_llm_mock("{}"))
    result = await svc.evaluate_answer(str(SESSION_ID), "any answer")

    assert "error" in result


# --- get_readiness ---

@patch("aegis.interview.service.InterviewRepository")
async def test_get_readiness_no_sessions(MockRepo):
    repo = MockRepo.return_value
    repo.get_readiness = AsyncMock(return_value={
        "company": None, "overall_score": None, "breakdown": {}, "top_weak_areas": []
    })
    repo.list_sessions = AsyncMock(return_value=[])

    svc = InterviewService(gateway=_llm_mock("{}"))
    result = await svc.get_readiness()

    assert result["readiness_level"] == "not-ready"
    assert "No interview prep" in result["summary"]


@patch("aegis.interview.service.InterviewRepository")
async def test_get_readiness_with_sessions(MockRepo):
    repo = MockRepo.return_value
    repo.get_readiness = AsyncMock(return_value={
        "company": "Stripe",
        "overall_score": 0.78,
        "breakdown": {"system-design": {"total": 3, "evaluated": 3, "avg_score": 0.78}},
        "top_weak_areas": ["distributed-systems"],
    })
    repo.list_sessions = AsyncMock(return_value=[
        {"question": QUESTION_TEXT, "session_type": "system-design", "score": 0.78},
    ])

    svc = InterviewService(gateway=_llm_mock(READINESS_RESPONSE))
    result = await svc.get_readiness(company="Stripe")

    assert result["readiness_level"] == "developing"
    assert "key_gaps" in result
    assert result["overall_score"] == 0.78


# --- helpers ---

def test_parse_json_plain():
    assert _parse_json('{"score": 0.8}') == {"score": 0.8}


def test_parse_json_fenced():
    text = '```json\n{"score": 0.8}\n```'
    assert _parse_json(text) == {"score": 0.8}


def test_parse_json_invalid():
    assert _parse_json("not json") == {}


def test_format_sessions_for_prompt():
    sessions = [
        {"question": "Design a rate limiter. Walk me through.", "session_type": "system-design", "score": 0.75},
        {"question": "Tell me about a conflict.", "session_type": "behavioral", "score": None},
    ]
    output = _format_sessions_for_prompt(sessions)
    assert "system-design" in output
    assert "0.75" in output
    assert "not evaluated" in output
