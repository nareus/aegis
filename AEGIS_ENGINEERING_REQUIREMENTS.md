# Aegis — Engineering Requirements

This document specifies what to build. It is a working document for an engineering agent (Claude Code) executing the implementation. It assumes the existing Aegis repo state (Phases 1–3 of the original plan: skeleton, source clients, LLM gateway).

## System summary

Aegis is a multi-agent system exposed via MCP. It runs two workflows that share the same agent infrastructure:

1. **Job analysis** — synchronous, triggered when a user adds a job. Researcher → Analyst → Critic with bounded refinement.
2. **Daily briefing** — scheduled, runs on cron. Parallel source fetch → Synthesizer → Critic with bounded refinement, fail-open under partial source failure.

Both workflows share: agent base class, LLM gateway, trace storage, eval harness, MCP surface.

## Tech stack (fixed)

- Python 3.12+, `uv` for package management
- LangGraph for workflow orchestration with `AsyncPostgresSaver` checkpointing
- FastMCP (stdio transport) for the MCP server
- Anthropic SDK direct (no LangChain wrappers)
- FastAPI for HTTP endpoints (health, trace viewer, eval history)
- PostgreSQL 16 (asyncpg, raw SQL with numbered migrations)
- Redis 7 (`redis.asyncio`) for response caching and rate-limit counters
- APScheduler for cron triggers
- httpx for external HTTP calls
- Loguru for structured logging
- pytest + pytest-asyncio + testcontainers-python for tests
- Docker Compose for local dev, Fly.io for production

## Coding conventions (non-negotiable)

- Full type annotations on every function, validated by mypy in CI
- Async everywhere — no sync I/O in request paths
- Result objects for expected failures (no exceptions for control flow); raise only for bugs
- Every agent call emits a trace span automatically via `AgentBase`
- Every LLM call has cost attribution to a span and contributes to a per-run cost total
- Configuration via environment variables and YAML files; no secrets in code
- Conventional commit messages
- Tests favor integration with testcontainers over mocking; mock only the external network boundary
- Loguru: bind `run_id` and `agent_name` for the duration of any agent call

## Repository structure (target)

```
aegis/
├── pyproject.toml
├── uv.lock
├── Dockerfile
├── docker-compose.yml
├── fly.toml
├── .env.example
├── README.md
├── docs/
│   ├── architecture.md
│   ├── eval_methodology.md
│   └── observability.md
├── migrations/
│   ├── 001_initial.sql              # existing — briefing_runs, briefing_latest
│   ├── 002_jobs.sql                 # existing — job_applications
│   └── 003_tracing_and_evals.sql    # NEW
├── evals/
│   ├── golden/
│   │   ├── job_fit.yaml
│   │   ├── critic_accuracy.yaml
│   │   └── briefing_quality.yaml
│   ├── judges/
│   │   ├── job_fit_judge.py
│   │   └── briefing_judge.py
│   └── run.py                       # eval runner CLI
├── src/aegis/
│   ├── __init__.py
│   ├── config.py
│   ├── logging.py
│   ├── app.py
│   ├── mcp_server.py
│   │
│   ├── agents/
│   │   ├── base.py                  # AgentBase — shared interface, tracing, cost
│   │   ├── researcher.py
│   │   ├── analyst.py
│   │   ├── critic.py
│   │   └── synthesizer.py
│   │
│   ├── workflows/
│   │   ├── job_analysis/
│   │   │   ├── graph.py
│   │   │   ├── state.py
│   │   │   └── service.py
│   │   └── briefing/
│   │       ├── graph.py
│   │       ├── state.py
│   │       └── service.py
│   │
│   ├── llm/
│   │   ├── gateway.py               # existing — extend for span integration
│   │   └── prompts.py
│   │
│   ├── tracing/
│   │   ├── spans.py                 # span emitter
│   │   ├── repository.py            # Postgres-backed storage
│   │   └── viewer.py                # HTML rendering
│   │
│   ├── sources/
│   │   ├── base.py                  # existing
│   │   ├── github.py                # existing
│   │   ├── hn.py                    # existing
│   │   ├── jobs_internal.py         # NEW — for briefing
│   │   └── gaps_internal.py         # NEW — cross-job skill aggregation
│   │
│   ├── jobs/
│   │   ├── repository.py
│   │   └── service.py
│   │
│   ├── db/
│   │   ├── engine.py                # existing
│   │   └── migrations.py
│   │
│   ├── api/
│   │   ├── health.py                # existing
│   │   ├── traces.py                # NEW — trace viewer endpoint
│   │   └── evals.py                 # NEW — eval history endpoint
│   │
│   └── scheduler/
│       └── runner.py                # existing — extend for nightly evals
│
└── tests/
    ├── conftest.py
    ├── unit/
    │   ├── test_agents_*.py
    │   ├── test_llm_gateway.py
    │   ├── test_tracing.py
    │   └── test_sources_*.py
    ├── integration/
    │   ├── test_job_analysis_e2e.py
    │   ├── test_briefing_e2e.py
    │   ├── test_mcp_server.py
    │   └── test_eval_harness.py
    └── fixtures/
        └── sample_payloads/
```

## Database schema (additions)

New migration: `migrations/003_tracing_and_evals.sql`

### agent_traces

Captures every agent call across the system. A workflow run produces a tree of spans (root span has `parent_span_id IS NULL`).

```sql
CREATE TABLE agent_traces (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID NOT NULL,
    parent_span_id  UUID REFERENCES agent_traces(id),
    agent_name      TEXT NOT NULL,                     -- 'researcher', 'analyst', 'critic', 'synthesizer'
    workflow        TEXT NOT NULL,                     -- 'job_analysis', 'briefing'
    input_payload   JSONB NOT NULL,
    output_payload  JSONB,
    error           TEXT,                              -- non-null implies failure
    cost_usd        NUMERIC(10, 6),
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    latency_ms      INTEGER,
    started_at      TIMESTAMPTZ NOT NULL,
    completed_at    TIMESTAMPTZ
);

CREATE INDEX idx_traces_run_id ON agent_traces(run_id);
CREATE INDEX idx_traces_workflow ON agent_traces(workflow);
CREATE INDEX idx_traces_started_at ON agent_traces(started_at);
```

### eval_runs

```sql
CREATE TABLE eval_runs (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    eval_name         TEXT NOT NULL,                   -- 'job_fit', 'critic_accuracy', 'briefing_quality'
    git_sha           TEXT,
    triggered_by      TEXT NOT NULL,                   -- 'ci', 'manual', 'scheduled'
    score             REAL NOT NULL,                   -- aggregate 0.0–1.0
    case_count        INTEGER NOT NULL,
    pass_count        INTEGER NOT NULL,
    detailed_results  JSONB,                           -- per-case results
    total_cost_usd    NUMERIC(10, 6),
    started_at        TIMESTAMPTZ NOT NULL,
    completed_at      TIMESTAMPTZ
);

CREATE INDEX idx_eval_runs_name_started ON eval_runs(eval_name, started_at DESC);
```

### eval_golden_cases

YAML in `evals/golden/` is the source of truth; this table mirrors it for analysis queries.

```sql
CREATE TABLE eval_golden_cases (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    eval_name       TEXT NOT NULL,
    case_id         TEXT NOT NULL,                     -- stable ID for case-level history
    input_payload   JSONB NOT NULL,
    expected_output JSONB NOT NULL,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (eval_name, case_id)
);
```

### Updates to job_applications

Add columns to link saved jobs to their analysis traces and to record refinement metadata.

```sql
ALTER TABLE job_applications
    ADD COLUMN critic_feedback   JSONB,
    ADD COLUMN refinement_count  INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN analysis_run_id   UUID;
```

`fit_analysis` already exists and contains the analyst's full structured output.

## Component requirements

### `agents/base.py` — AgentBase

Abstract base class for every agent. Concrete agents implement `_run`. The base handles tracing, cost attribution, and error surfacing.

Interface contract:

- `__init__(self, llm_gateway, tracer, name: str, model: str, max_tokens: int)`
- `async def run(self, run_id: UUID, parent_span_id: UUID | None, input_payload: dict) -> AgentResult`
  - Emits a span automatically with timing, cost, input, output
  - Catches exceptions from `_run`, records as `error` on the span, returns `AgentResult(ok=False, error=...)`
  - Never raises for expected agent failures
- `async def _run(self, input_payload: dict) -> dict` — abstract; concrete agents implement this

`AgentResult` is a dataclass: `ok: bool`, `output: dict | None`, `error: str | None`, `span_id: UUID`, `cost_usd: Decimal`, `latency_ms: int`.

Each concrete agent has its own model and max_tokens defaults but they're overridable via env vars (`AEGIS_LLM_MODEL_ANALYST`, etc.).

### `tracing/spans.py` — span emitter

- `class Tracer` with `async def start_span(...) -> Span` and `async def complete_span(span_id, output, cost, error=None)`
- A `Span` context manager that handles start/complete automatically
- Spans are written to Postgres via `tracing/repository.py`
- The tracer is a singleton-per-process, accessed via dependency injection in agents

### `tracing/repository.py` — span storage

- `async def insert_span(span: SpanRecord)`
- `async def update_span(span_id: UUID, output, cost, error, completed_at)`
- `async def get_run_tree(run_id: UUID) -> list[SpanRecord]` — returns all spans for a run, ordered for tree reconstruction
- All operations use the existing `db/engine.py` asyncpg pool

### `tracing/viewer.py` — HTML trace viewer

- Function: given a `run_id`, render an HTML page showing the span tree
- Each span shows: agent_name, latency, cost, input_payload (collapsible), output_payload (collapsible), error (if any)
- Spans nested visually by `parent_span_id`
- Plain HTML, no JS framework — Jinja2 template is sufficient
- Mounted at `GET /trace/<run_id>` via `api/traces.py`

### `agents/researcher.py`

Input: `{ "url_or_text": str, "profile": dict }`

Behavior:
1. If `url_or_text` looks like a URL, fetch it via `web_fetch` (use httpx with reasonable timeout/retry)
2. If it's text, treat it as the JD body directly
3. Optionally fetch additional company context (deferrable to v1.1; for v1, just use the JD content)
4. Use the LLM to extract structured information

Output:
```json
{
  "company": "string",
  "role": "string",
  "location": "string | null",
  "remote": "bool | null",
  "salary_range": "string | null",
  "tech_stack": ["string", ...],
  "responsibilities": ["string", ...],
  "requirements": ["string", ...],
  "company_context": "string | null",
  "raw_jd_text": "string"
}
```

Errors: if fetch fails, return `ok=False` with reason; the workflow handles fallback.

### `agents/analyst.py`

Input: `{ "researched_job": <Researcher output>, "profile": dict, "previous_critic_feedback": dict | null }`

Behavior:
1. Compare the researched job against the profile
2. Score fit (0.0–1.0) with explicit reasoning
3. Identify matching skills and gap skills
4. If `previous_critic_feedback` is present (refinement loop), incorporate it into the new analysis
5. Single LLM call, structured JSON output

Output:
```json
{
  "fit_score": 0.78,
  "reasoning": "string — explicit logic linking JD requirements to profile",
  "matching_skills": ["string", ...],
  "gap_skills": ["string", ...],
  "critical_gaps": ["string", ...],   // gaps that materially affect the score
  "deal_breakers_present": ["string", ...],   // hard exclusions found in the JD
  "recommendation": "apply | review_more | skip",
  "notes": "string | null"
}
```

For v1, the `profile` dict is loaded from a YAML file specified by `AEGIS_PROFILE_PATH`. The exact profile schema is intentionally not specified in this document — the analyst should treat the profile as opaque structured input and let the prompt define how it's interpreted. A separate document will define the profile schema.

### `agents/critic.py`

Input: `{ "researched_job": <Researcher output>, "analysis": <Analyst output>, "profile": dict }`

Critically: the Critic does NOT see prior critic feedback or the analyst's reasoning chain — only the most recent analyst output and the original job. This is the design point.

Behavior:
1. Independently re-evaluate the analyst's score for plausibility
2. Check for common defects (defined in prompt):
   - Keyword-overlap inflation (matching on superficial keyword matches without real fit)
   - Missed deal-breakers in the JD
   - Score not consistent with the magnitude of identified gaps
   - Misclassified role (e.g., calling a data engineering role a backend role)
3. Return either approval or specific issues

Output:
```json
{
  "verdict": "approve | revise",
  "issues": [
    { "type": "string", "description": "string", "severity": "low | medium | high" }
  ],
  "confidence": 0.0
}
```

If `verdict == "revise"` and refinement count is below max (configured, default 2), the workflow loops back to the analyst with this feedback.

### `agents/synthesizer.py`

Input: `{ "source_outputs": dict, "profile": dict }` where `source_outputs` is a map from source name → fetched data.

Behavior:
1. Read each source's output, ignoring any sources that returned `ok=False`
2. Produce a markdown briefing with sections: Action Required, Job Search, Cross-Job Intelligence, GitHub, Reading
3. Single LLM call, markdown output

Output:
```json
{
  "briefing_md": "string",
  "sections_included": ["string", ...],
  "sections_omitted": ["string", ...],     // sources that failed
  "summary_line": "string"                 // one-line top priority
}
```

### `agents/critic.py` for briefings

The same Critic class handles briefing review with a different prompt. Configurable via `task` parameter at construction. Briefing critic checks:
- Actionability (does it tell me what to do?)
- Specificity (concrete names and numbers, not generic advice)
- Prioritization (most important thing first)

Output schema is identical to job-analysis critic.

### `workflows/job_analysis/graph.py`

LangGraph state machine. Nodes: `researcher`, `analyst`, `critic`, `persist`.

State (TypedDict):
```python
class JobAnalysisState(TypedDict):
    run_id: UUID
    input: dict                      # original {url_or_text}
    profile: dict
    researched: dict | None
    analysis: dict | None
    critic_feedback: dict | None
    refinement_count: int
    final_analysis: dict | None
    error: str | None
```

Topology:
```
START → researcher → analyst → critic
                        ↑          |
                        |          v
                        +---- maybe_refine
                                   |
                                   v
                                persist → END
```

`maybe_refine` is a conditional edge:
- If `critic.verdict == "approve"` → persist
- If `critic.verdict == "revise"` and `refinement_count < MAX_REFINEMENTS` → analyst (with critic feedback in state)
- If `critic.verdict == "revise"` and `refinement_count >= MAX_REFINEMENTS` → persist (with critic feedback recorded but not blocking)

Configuration: `AEGIS_MAX_REFINEMENTS=2`.

### `workflows/job_analysis/service.py`

Public API: `async def analyze_job(url_or_text: str) -> JobAnalysisResult`

- Generates a `run_id`
- Loads profile
- Initializes state
- Runs the graph with the run_id as the LangGraph thread
- Persists the final job to `job_applications`
- Returns the job ID and a summary

### `workflows/briefing/graph.py`

LangGraph state machine with parallel fan-out.

State:
```python
class BriefingState(TypedDict):
    run_id: UUID
    profile: dict
    source_outputs: dict             # {source_name: result_or_error}
    sources_ok: list[str]
    sources_failed: dict             # {source_name: error_message}
    draft_briefing: dict | None
    critic_feedback: dict | None
    refinement_count: int
    final_briefing: dict | None
    is_degraded: bool                # true if all sources failed
```

Topology (matches the existing graph plus refinement on synthesizer output):
```
START → init_run → [fetch_jobs ‖ fetch_lc ‖ fetch_github ‖ fetch_hn] → check_fetches
                                                                            |
                                                +---------------------------+
                                                |                           |
                                       all sources failed              ≥1 source ok
                                                |                           |
                                                v                           v
                                       degraded_briefing             synthesizer → critic
                                                |                                    ↑   |
                                                |                                    |   v
                                                |                                  maybe_refine
                                                |                                    |
                                                +-----------+------------------------+
                                                            v
                                                         persist → END
```

Source fetches run in parallel (LangGraph fan-out). `check_fetches` is a barrier node. `maybe_refine` is identical in shape to the job analysis variant.

`degraded_briefing` produces a minimal markdown explicitly noting which sources failed and why; no LLM call is made if all sources failed.

### `workflows/briefing/service.py`

Public API: `async def run_briefing(triggered_by: str) -> BriefingRunResult`

- Generates `run_id`, loads profile, initializes state
- Runs graph, persists to `briefing_runs` and updates `briefing_latest`
- Returns run summary (briefing_md, total cost, sources status)

### `sources/jobs_internal.py`

Reads from `job_applications` to feed the briefing.

Output shape:
```json
{
  "stale_applications": [{"job_id": "...", "company": "...", "role": "...", "applied_date": "...", "days_since_activity": 12}],
  "top_fit_unapplied": [{"job_id": "...", "company": "...", "role": "...", "fit_score": 0.85}],
  "recent_status_changes": [{"job_id": "...", "from_status": "...", "to_status": "...", "at": "..."}]
}
```

Stale = `last_activity` older than 7 days AND status in (`applied`, `screening`, `interviewing`).
Top-fit unapplied = `fit_score >= 0.7` AND `status == 'saved'`, ordered by fit_score desc, limit 5.

### `sources/gaps_internal.py`

The cross-job intelligence feature. Aggregates skill demand across saved jobs.

Output shape:
```json
{
  "top_demanded_missing_skills": [
    {"skill": "kafka", "job_count": 7, "avg_fit_score_when_required": 0.62, "example_jobs": ["job_id1", "job_id2"]},
    {"skill": "go", "job_count": 5, "avg_fit_score_when_required": 0.58, "example_jobs": [...]}
  ],
  "top_present_skills": [
    {"skill": "python", "job_count": 14},
    {"skill": "aws", "job_count": 11}
  ]
}
```

Aggregation:
- Read all jobs in `job_applications` with `status != 'rejected'` and `status != 'withdrawn'`
- Pull `gap_skills` from each `fit_analysis` JSONB
- Count occurrences across all jobs
- For each skill, compute the average `fit_score` of jobs where it was a gap (signals: "if I had this skill, my average fit on those jobs would improve")
- Return top 10 by count

This is intentionally simple to start. The LLM-extracted skill names will be inconsistent (`"kubernetes"` vs `"k8s"` vs `"K8s"`); a normalization pass should be added but can be naive (lowercase, basic alias map) for v1.

### `llm/gateway.py` updates

The existing gateway has cost tracking. Extend it to:
- Accept a `span_id` parameter on each call
- After each call, update the corresponding span with `cost_usd`, `input_tokens`, `output_tokens`
- Enforce per-run budget: maintain a running cost-per-run counter; raise `BudgetExceededError` if the next call would exceed `AEGIS_LLM_MAX_COST_USD_PER_RUN`

Budget enforcement is checked before the call, not after. Calls are billed against the run that owns them via `run_id`.

### `evals/run.py`

CLI entry point: `uv run python -m aegis.evals.run --suite <name> [--cases <case_id>...] [--no-persist]`

Suites: `job_fit`, `critic_accuracy`, `briefing_quality`, `all`.

Per case, the runner:
1. Loads input from `evals/golden/<suite>.yaml`
2. Runs the relevant workflow with that input
3. Compares output against `expected_output` using the suite's judge
4. Records pass/fail and per-case score

After all cases, it persists an `eval_runs` row with aggregate score.

Parallelism: process cases concurrently with a semaphore (default 5). Total cost capped at `AEGIS_EVAL_MAX_COST_USD`; abort and persist partial results if exceeded.

Exit code: 0 if score >= prior best - `AEGIS_EVAL_REGRESSION_THRESHOLD`, 1 otherwise. Used by CI.

### `evals/judges/job_fit_judge.py`

Given an analyst output and an expected output, score it using a weighted combination:

- **Score-in-range (40%)**: 1.0 if `expected_output.score_range[0] <= actual_score <= expected_output.score_range[1]`, else falloff proportional to distance
- **Critical skills identified (30%)**: precision/recall of `actual.matching_skills` vs `expected.required_matching_skills`
- **Critical gaps identified (30%)**: precision/recall of `actual.critical_gaps` vs `expected.required_gaps`

A case passes if its weighted score is `>= 0.7`.

### `evals/judges/briefing_judge.py`

LLM-as-judge against a rubric:
- Actionability (1–5): does the briefing tell the reader what to do?
- Specificity (1–5): concrete names, numbers, dates vs generic statements
- Prioritization (1–5): is the most important item first?

Final score: `(actionability + specificity + prioritization) / 15`. Pass threshold: 0.7.

The judge prompt is itself a versioned prompt in `evals/judges/`. Periodic validation against my own ratings on a subset is recommended but not automated for v1.

### `mcp_server.py`

FastMCP stdio server exposing:

Tools:
- `add_job(url_or_text: str) -> {job_id, fit_score, recommendation, run_id}`
- `list_jobs(status: str | None = None, min_fit_score: float | None = None) -> list[JobSummary]`
- `update_status(job_id: str, status: str, notes: str | None = None) -> {ok}`
- `get_follow_ups() -> list[StaleApplication]`
- `get_skill_gaps() -> {top_demanded_missing_skills, top_present_skills}`
- `run_briefing() -> {run_id, briefing_md, sources_status}`
- `get_latest_briefing() -> {briefing_md, run_id, generated_at}`
- `get_trace(run_id: str) -> {trace_url, spans_summary}`

Resources:
- `briefing://latest`
- `aegis://jobs/dashboard`
- `aegis://gaps/skills`

Prompts:
- `morning_standup()` — instructs Claude to fetch the latest briefing and read it back with priorities

All tools are thin wrappers around `workflows/*/service.py` and `jobs/service.py`. No business logic in the MCP layer.

### `api/traces.py`

- `GET /trace/<run_id>` — renders HTML trace viewer
- `GET /trace/<run_id>/json` — returns raw span data as JSON

### `api/evals.py`

- `GET /evals/history` — renders an HTML page with a chart of eval scores per commit, per suite. Use a simple charting library (Chart.js via CDN) — no build step required.
- `GET /evals/runs/<eval_run_id>` — detail page for a specific eval run

### `scheduler/runner.py` extensions

- Existing: 7am Singapore briefing cron
- Add: 2am Singapore nightly eval cron (`AEGIS_EVAL_NIGHTLY_CRON`)

## Testing requirements

### Unit tests

- `tests/unit/test_agents_base.py` — span emission, cost tracking, error handling
- `tests/unit/test_agents_<name>.py` — one per agent, mocking only the LLM gateway, asserting structured output shape
- `tests/unit/test_tracing.py` — span tree reconstruction, parent linkage
- `tests/unit/test_llm_gateway.py` — budget enforcement, cost accumulation
- `tests/unit/test_sources_gaps_internal.py` — aggregation logic with synthetic job data

### Integration tests (testcontainers Postgres + Redis)

- `tests/integration/test_job_analysis_e2e.py` — full workflow with a recorded JD fixture; LLM mocked at the gateway level with deterministic responses; asserts trace tree shape and persisted `job_applications` row
- `tests/integration/test_briefing_e2e.py` — full briefing with mixed source success/failure; asserts fail-open behavior
- `tests/integration/test_briefing_all_sources_failed.py` — degraded path
- `tests/integration/test_mcp_server.py` — exercises each tool via the MCP protocol
- `tests/integration/test_eval_harness.py` — runs a 3-case mini-suite end-to-end and asserts `eval_runs` row is written

### CI

GitHub Actions workflow:
1. Lint (ruff)
2. Type check (mypy)
3. Unit tests
4. Integration tests
5. Eval suite (cost-capped to `AEGIS_EVAL_MAX_COST_USD`)
6. Eval regression check vs `main` — fails if score drops > `AEGIS_EVAL_REGRESSION_THRESHOLD`

## Configuration (env vars)

```
# Core
AEGIS_ENV=local
LOG_LEVEL=INFO

# LLM
ANTHROPIC_API_KEY=
AEGIS_LLM_MODEL_RESEARCHER=claude-sonnet-4-5
AEGIS_LLM_MODEL_ANALYST=claude-sonnet-4-5
AEGIS_LLM_MODEL_CRITIC=claude-sonnet-4-5
AEGIS_LLM_MODEL_SYNTHESIZER=claude-sonnet-4-5
AEGIS_LLM_MAX_COST_USD_PER_RUN=0.50

# Profile
AEGIS_PROFILE_PATH=./profile.yaml

# Workflows
AEGIS_MAX_REFINEMENTS=2

# Data sources
GITHUB_TOKEN=
GITHUB_USERNAME=

# Infrastructure
DATABASE_URL=postgresql://aegis:aegis@localhost:5432/aegis
REDIS_URL=redis://localhost:6379/0

# Scheduler
AEGIS_BRIEFING_CRON=0 7 * * *
AEGIS_EVAL_NIGHTLY_CRON=0 2 * * *
AEGIS_TIMEZONE=Asia/Singapore

# Eval
AEGIS_EVAL_REGRESSION_THRESHOLD=0.03
AEGIS_EVAL_MAX_COST_USD=2.00
```

## Build order (for the implementing agent)

Each phase has a clear "done" gate. Do not advance until the gate is met.

### Phase A — Tracing infrastructure

1. Apply migration `003_tracing_and_evals.sql`
2. Implement `tracing/spans.py`, `tracing/repository.py`, `tracing/viewer.py`
3. Implement `agents/base.py` — AgentBase with automatic span emission
4. Refactor `llm/gateway.py` to integrate with span emission
5. Add `api/traces.py` with `/trace/<run_id>` route
6. Tests: `test_tracing.py`, `test_agents_base.py`, `test_llm_gateway.py`

**Gate:** can run a stub agent, retrieve its trace via HTTP, see input/output/cost/latency rendered.

### Phase B — Job analysis pipeline

1. Implement `agents/researcher.py`, `agents/analyst.py`, `agents/critic.py`
2. Implement `workflows/job_analysis/state.py`, `graph.py`, `service.py`
3. Update `jobs/repository.py` and `jobs/service.py` to persist analyzer output and link `analysis_run_id`
4. Add MCP tools: `add_job`, `list_jobs`, `update_status`, `get_follow_ups`, `get_trace`
5. Profile YAML loader in `config.py` (treat as opaque dict)
6. Tests: per-agent unit tests, `test_job_analysis_e2e.py`, `test_mcp_server.py`

**Gate:** end-to-end run from MCP `add_job` produces a persisted job, full trace viewable, all tests pass.

### Phase C — Eval harness

1. Implement `evals/run.py`, `evals/judges/job_fit_judge.py`
2. Hand-author `evals/golden/job_fit.yaml` with ~50 cases
3. CI workflow with eval step
4. `eval_runs` persistence
5. Add `api/evals.py` with `/evals/history` chart
6. Tests: `test_eval_harness.py`

**Gate:** eval suite runs in CI, baseline score recorded, regression check working.

### Phase D — Briefing pipeline

1. Implement `sources/jobs_internal.py`, `sources/gaps_internal.py`
2. Implement `agents/synthesizer.py`
3. Reuse `agents/critic.py` with task=briefing
4. Implement `workflows/briefing/state.py`, `graph.py`, `service.py`
5. APScheduler cron for daily briefing
6. MCP tools: `run_briefing`, `get_latest_briefing`, `get_skill_gaps`
7. Resource: `briefing://latest`
8. Tests: `test_briefing_e2e.py`, `test_briefing_all_sources_failed.py`

**Gate:** scheduled briefing runs, accessible via MCP, fail-open behavior verified by integration test.

### Phase E — Briefing eval + critic eval

1. Hand-author `evals/golden/briefing_quality.yaml` with ~20 cases
2. Hand-author `evals/golden/critic_accuracy.yaml` with ~30 cases
3. Implement `evals/judges/briefing_judge.py`
4. Critic accuracy judge
5. Add both suites to CI

**Gate:** all three eval suites green in CI, score history visible at `/evals/history`.

### Phase F — Production deployment

1. Multi-stage `Dockerfile`
2. `fly.toml` configuration
3. Postgres + Redis on Fly.io (or external managed)
4. Production smoke test
5. Per-agent cost dashboard at `/costs`

**Gate:** Aegis is running on Fly.io, briefing cron firing, MCP accessible from local Claude Desktop pointed at production.

## Out of scope for v1

These are explicitly deferred:
- LeetCode tracker
- Interview prep mock generation
- Preference learning / calibration agent (separate document forthcoming)
- Consistency checker for historical evaluations
- Multi-source company research in the Researcher (web fetch on JD URL only is sufficient)
- Web UI beyond the trace viewer and eval history pages
- Authentication on HTTP endpoints (single-user local/private Fly app)

## Open questions for the implementing agent

The implementing agent should flag for clarification rather than guess:

1. The exact `profile.yaml` schema (deferred to a separate document — v1 should treat it as opaque dict)
2. The skill normalization alias map for `gaps_internal.py` (start with naive lowercase + small hardcoded map)
3. Whether to use Anthropic prompt caching for repeated profile data (recommended optimization but not required for v1 correctness)
4. Specific prompt text for each agent (the implementing agent should draft these and iterate via the eval harness, not freeze them upfront)
