"""Run a YAML-defined eval against the job_analysis pipeline.

Loads cases from evals/<eval_name>/cases/*.yaml, invokes the
Researcher → Analyst → Critic graph for each, checks the `expected`
assertions, and writes a summary row to `eval_runs`. Spans for each case
land in `agent_traces` (look them up by run_id printed below).

Usage:
    uv run python scripts/run_eval.py job_fit_v1
    uv run python scripts/run_eval.py job_fit_v1 --triggered-by=ci
"""

import argparse
import asyncio
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import yaml

from aegis.agents.analyst import AnalystAgent
from aegis.agents.critic import CriticAgent
from aegis.agents.researcher import ResearcherAgent
from aegis.db.engine import close_pool, get_pool
from aegis.llm.gateway import LLMGateway
from aegis.profile import load_profile
from aegis.workflows.job_analysis.graph import build_job_analysis_graph
from aegis.workflows.job_analysis.state import JobAnalysisState

EVALS_DIR = Path(__file__).resolve().parent.parent / "evals"


# ── case loading ────────────────────────────────────────────────────────────

def load_cases(eval_name: str) -> list[dict]:
    cases_dir = EVALS_DIR / eval_name / "cases"
    if not cases_dir.exists():
        raise SystemExit(f"no cases directory at {cases_dir}")
    cases = [yaml.safe_load(p.read_text()) for p in sorted(cases_dir.glob("*.yaml"))]
    if not cases:
        raise SystemExit(f"no case files under {cases_dir}")
    return cases


# ── workflow invocation (no persistence to job_applications) ────────────────

async def run_workflow(url_or_text: str) -> tuple[UUID, dict | None, float, str | None]:
    """Run the job_analysis graph once. Returns (run_id, analysis, cost, error)."""
    run_id = uuid4()
    gateway = LLMGateway()
    graph = build_job_analysis_graph(
        ResearcherAgent(gateway),
        AnalystAgent(gateway),
        CriticAgent(gateway),
    ).compile()

    initial: JobAnalysisState = {
        "run_id": run_id,
        "input": {"url_or_text": url_or_text},
        "profile": load_profile().as_prompt(),
        "researched": None,
        "analysis": None,
        "critic_feedback": None,
        "refinement_count": 0,
        "final_analysis": None,
        "error": None,
        "total_cost_usd": 0.0,
    }
    final: JobAnalysisState = await graph.ainvoke(initial)
    return (
        run_id,
        final.get("final_analysis"),
        float(final.get("total_cost_usd", 0.0)),
        final.get("error"),
    )


# ── assertions ──────────────────────────────────────────────────────────────

def check(analysis: dict | None, expected: dict) -> list[str]:
    """Return a list of failure messages; empty list means the case passed."""
    failures: list[str] = []

    if analysis is None:
        return ["analysis is null (workflow error)"]

    if "recommendation" in expected:
        got = analysis.get("recommendation")
        if got != expected["recommendation"]:
            failures.append(f"recommendation: got {got!r}, expected {expected['recommendation']!r}")

    if "fit_score" in expected:
        fs = analysis.get("fit_score")
        bounds = expected["fit_score"]
        lo = float(bounds.get("min", 0.0))
        hi = float(bounds.get("max", 1.0))
        if fs is None or not (lo <= float(fs) <= hi):
            failures.append(f"fit_score: got {fs}, expected in [{lo}, {hi}]")

    if "must_include_skills" in expected:
        got_skills = {s.lower() for s in (analysis.get("matching_skills") or [])}
        for required in expected["must_include_skills"]:
            if required.lower() not in got_skills:
                failures.append(f"matching_skills: missing {required!r}")

    if expected.get("must_not_have_deal_breakers"):
        present = analysis.get("deal_breakers_present") or []
        if present:
            failures.append(f"deal_breakers_present: {present!r}")

    return failures


# ── eval_runs persistence ───────────────────────────────────────────────────

async def write_eval_run(
    *,
    eval_name: str,
    triggered_by: str,
    score: float,
    case_count: int,
    pass_count: int,
    detailed_results: list[dict],
    total_cost_usd: float,
    started_at: datetime,
    completed_at: datetime,
) -> UUID:
    git_sha = _git_sha()
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO eval_runs
            (eval_name, git_sha, triggered_by, score, case_count, pass_count,
             detailed_results, total_cost_usd, started_at, completed_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10)
        RETURNING id
        """,
        eval_name,
        git_sha,
        triggered_by,
        score,
        case_count,
        pass_count,
        json.dumps(detailed_results, default=str),
        total_cost_usd,
        started_at,
        completed_at,
    )
    return row["id"]


def _git_sha() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        )
        return out.decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


# ── main ────────────────────────────────────────────────────────────────────

async def main(eval_name: str, triggered_by: str) -> int:
    cases = load_cases(eval_name)
    print(f"Running {len(cases)} case(s) for eval '{eval_name}'...\n")

    started_at = datetime.now(timezone.utc)
    detailed: list[dict] = []
    pass_count = 0
    total_cost = 0.0

    for case in cases:
        case_id = case["case_id"]
        url_or_text = case["input"]["url_or_text"]
        expected = case["expected"]

        run_id, analysis, cost, error = await run_workflow(url_or_text)
        total_cost += cost

        if error:
            failures = [f"workflow error: {error}"]
        else:
            failures = check(analysis, expected)

        passed = not failures
        if passed:
            pass_count += 1

        status_glyph = "PASS" if passed else "FAIL"
        print(f"  [{status_glyph}] {case_id}  (run_id={run_id}, cost=${cost:.4f})")
        for f in failures:
            print(f"          - {f}")

        detailed.append({
            "case_id": case_id,
            "run_id": str(run_id),
            "passed": passed,
            "failures": failures,
            "analysis": analysis,
            "cost_usd": cost,
        })

    completed_at = datetime.now(timezone.utc)
    score = pass_count / len(cases) if cases else 0.0

    eval_run_id = await write_eval_run(
        eval_name=eval_name,
        triggered_by=triggered_by,
        score=score,
        case_count=len(cases),
        pass_count=pass_count,
        detailed_results=detailed,
        total_cost_usd=total_cost,
        started_at=started_at,
        completed_at=completed_at,
    )

    print(
        f"\n{eval_name}: {pass_count}/{len(cases)} passed "
        f"(score={score:.2f}, cost=${total_cost:.4f}, eval_run_id={eval_run_id})"
    )
    return 0 if pass_count == len(cases) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run an Aegis eval suite.")
    parser.add_argument("eval_name", help="Directory name under evals/, e.g. job_fit_v1")
    parser.add_argument(
        "--triggered-by", default="manual",
        help="Who/what triggered this run (manual, ci, cron). Default: manual.",
    )
    args = parser.parse_args()

    try:
        rc = asyncio.run(main(args.eval_name, args.triggered_by))
    finally:
        asyncio.run(close_pool())
    sys.exit(rc)
