# Aegis -- MCP-Native Agentic Platform for SWE Career Growth

## Project overview

Aegis is a personal agent platform that helps you become a better backend/AI engineer and land the right job. It exposes autonomous agents as MCP (Model Context Protocol) tools, resources, and prompts so any MCP client (Claude Desktop, Claude Code, Cursor) can interact with them.

**Three core capabilities:**

1. **Job Tracker** -- Add jobs from LinkedIn URLs or pasted JDs. LLM parses the posting, scores fit against your profile, identifies skill gaps, and tracks application status with follow-up reminders.
2. **LeetCode Tracker** -- Track solved problems by pattern (DP, graphs, sliding window, etc.), identify weak areas, get recommendations on what to practice next.
3. **Interview Prep Agent** -- Mock system design and behavioral questions tailored to your weak areas and target companies. Tracks readiness per company.

The **Daily Briefing Agent** ties everything together as a personal dashboard: stale applications, LeetCode gaps, upcoming interviews, plus a small section for GitHub activity and one relevant HN story.

## Tech stack

- **Language**: Python 3.12+, `uv` for package management
- **Agent framework**: LangGraph (stateful graph-based agent orchestration)
- **MCP server**: FastMCP (Python MCP SDK) with stdio transport for Claude Desktop/Code
- **LLM provider**: Anthropic Claude API (direct SDK, no LangChain wrappers)
- **API layer**: FastAPI (health checks, manual triggers, cron target)
- **State persistence**: PostgreSQL 16 (job tracker, LeetCode progress, briefing runs, LangGraph checkpoints)
- **Caching**: Redis 7 (API response caching, rate limit tracking)
- **Scheduling**: APScheduler (cron-triggered agent runs)
- **Testing**: pytest + pytest-asyncio + testcontainers-python (Postgres, Redis)
- **Logging**: Loguru (JSON output in prod, human-readable locally)
- **Database access**: Raw asyncpg with numbered SQL migrations
- **Infrastructure**: Docker Compose (local dev), Fly.io (production)

## Architecture

### Layer 1: MCP server (the public interface)

**Job Tracker tools:**
- `add_job(url_or_text)` -- Parse a LinkedIn URL or pasted JD, LLM extracts structured data, scores fit against profile, saves to tracker
- `list_jobs(status?)` -- List tracked jobs, optionally filtered by status
- `update_job(job_id, status, notes?)` -- Update application status
- `get_follow_ups()` -- List stale applications needing follow-up (no activity 7+ days)
- `get_job(job_id)` -- Get full details including fit score, gaps, prep notes

**LeetCode Tracker tools:**
- `log_problem(title_slug, difficulty, patterns, solved)` -- Log a solved/attempted problem
- `get_progress()` -- Progress summary by pattern with weak areas highlighted
- `suggest_next()` -- LLM recommends next problem to practice based on gaps

**Interview Prep tools:**
- `mock_system_design(company?, topic?)` -- Generate a system design question tailored to target company/weak areas
- `mock_behavioral(company?)` -- Generate a behavioral question with STAR framework guidance
- `evaluate_answer(question, answer)` -- LLM evaluates your answer with specific feedback
- `get_readiness(company?)` -- Readiness score for a company based on prep done

**Briefing tools:**
- `run_briefing()` -- Trigger a fresh daily briefing
- `get_latest_briefing()` -- Return the most recent briefing
- `list_recent_runs(limit)` -- List recent runs

**Resources:**
- `briefing://latest` -- Most recent briefing as markdown
- `aegis://jobs/dashboard` -- Job application statuses, fit scores
- `aegis://jobs/reminders` -- Stale applications needing follow-up
- `aegis://leetcode/progress` -- Progress by pattern, weak areas
- `aegis://interview/readiness` -- Per-company readiness scores

**Prompts:**
- `morning_standup()` -- "Give me my daily briefing and tell me what to focus on first."

**Claude Desktop config** (stdio transport):
```json
{
  "mcpServers": {
    "aegis": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/aegis", "python", "-m", "aegis.mcp_server"]
    }
  }
}
```

### Layer 2: Agent runtime (LangGraph)

- **BriefingService**: Single entry point for daily briefing runs
- **JobAnalyzer**: LLM-powered JD parsing and fit scoring
- **InterviewPrepAgent**: Multi-turn mock interview sessions (v0.2)
- **Scheduler**: APScheduler runs briefing on cron schedule
- **LangGraph checkpointing**: PostgreSQL-backed `AsyncPostgresSaver`
- **LLM Gateway**: Direct Anthropic SDK wrapper with cost tracking and budget caps

### Layer 3: Infrastructure

- PostgreSQL 16: Job tracker, LeetCode progress, briefing runs, LangGraph checkpoints
- Redis 7: API response caching, rate limit counters
- Docker Compose: One-command local setup
- Fly.io: Production deployment

## User profile

Stored in config, used by LLM to score job fit and tailor interview prep:

```bash
# --- Profile (used for job fit scoring and interview prep) ---
AEGIS_PROFILE_SKILLS=python,golang,distributed-systems,postgresql,redis,docker,kubernetes,fastapi,async-programming,system-design
AEGIS_PROFILE_TARGET_ROLES=backend-engineer,platform-engineer,ai-engineer
AEGIS_PROFILE_EXPERIENCE_YEARS=3
AEGIS_PROFILE_PREFERRED_LOCATIONS=singapore,remote
AEGIS_PROFILE_DEAL_BREAKERS=php,wordpress
```

## Database schema

### job_applications
```sql
CREATE TABLE job_applications (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company         TEXT NOT NULL,
    role            TEXT NOT NULL,
    url             TEXT,
    source_text     TEXT,                       -- raw JD text for reference
    status          TEXT NOT NULL DEFAULT 'saved',  -- saved|applied|screening|interviewing|offer|rejected|withdrawn
    fit_score       REAL,                       -- 0.0-1.0 LLM-assessed fit
    fit_analysis    JSONB,                      -- {"matching_skills": [...], "missing_skills": [...], "notes": "..."}
    tech_stack      TEXT[],                     -- extracted from JD
    salary_range    TEXT,
    location        TEXT,
    remote          BOOLEAN,
    notes           TEXT,
    applied_date    TIMESTAMPTZ,
    last_activity   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_jobs_status ON job_applications(status);
CREATE INDEX idx_jobs_last_activity ON job_applications(last_activity);
CREATE INDEX idx_jobs_fit_score ON job_applications(fit_score DESC);
```

### leetcode_problems
```sql
CREATE TABLE leetcode_problems (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,
    title_slug      TEXT NOT NULL UNIQUE,
    difficulty      TEXT NOT NULL,              -- Easy|Medium|Hard
    patterns        TEXT[] NOT NULL,            -- ["dynamic-programming", "arrays", "hash-table"]
    url             TEXT,
    solved          BOOLEAN NOT NULL DEFAULT false,
    attempts        INTEGER NOT NULL DEFAULT 1,
    time_complexity TEXT,                       -- user's solution complexity
    notes           TEXT,                       -- what you learned
    solved_at       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_leetcode_patterns ON leetcode_problems USING GIN(patterns);
CREATE INDEX idx_leetcode_difficulty ON leetcode_problems(difficulty);
CREATE INDEX idx_leetcode_solved ON leetcode_problems(solved);
```

### interview_sessions (v0.2)
```sql
CREATE TABLE interview_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          UUID REFERENCES job_applications(id),
    session_type    TEXT NOT NULL,              -- system-design|behavioral
    question        TEXT NOT NULL,
    answer          TEXT,
    feedback        TEXT,
    score           REAL,                       -- 0.0-1.0
    weak_areas      TEXT[],                     -- identified gaps
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### briefing_runs
```sql
CREATE TABLE briefing_runs (
    run_id          UUID PRIMARY KEY,
    triggered_at    TIMESTAMPTZ NOT NULL,
    trigger_source  TEXT NOT NULL,
    status          TEXT NOT NULL,
    briefing_md     TEXT,
    quality_score   REAL,
    iterations      INTEGER NOT NULL DEFAULT 1,
    sources_ok      TEXT[] NOT NULL DEFAULT '{}',
    sources_failed  JSONB NOT NULL DEFAULT '{}',
    total_cost_usd  NUMERIC(10, 6) NOT NULL DEFAULT 0,
    total_latency_ms INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### briefing_latest
```sql
CREATE TABLE briefing_latest (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    run_id  UUID NOT NULL REFERENCES briefing_runs(run_id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

LangGraph checkpointer owns its own tables via `AsyncPostgresSaver.setup()`.

## Daily Briefing Agent -- redesigned

The briefing now pulls primarily from **your own data**, not just external feeds.

### Data sources for briefing

1. **Job tracker** (internal DB): stale applications, recent status changes, top-fit jobs not yet applied to
2. **LeetCode progress** (internal DB): weak patterns, streak status, suggested next problem
3. **Interview readiness** (internal DB): upcoming interviews, prep gaps per company
4. **GitHub** (external API): notifications, recent activity
5. **Hacker News** (external API): 1-3 relevant stories (small section, not the focus)

### Briefing sections

```markdown
## Action Required
- 3 applications with no activity in 7+ days [follow up]
- Interview with Stripe in 2 days -- no system design prep done yet

## Job Search
- 2 new high-fit jobs added this week (Stripe: 0.9, Datadog: 0.85)
- Gap alert: 3 jobs require Kafka experience -- consider learning

## LeetCode
- Weakest pattern: Dynamic Programming (2/15 solved)
- Suggested: "Coin Change" (Medium, DP) -- most common in interviews
- Streak: 12 days

## GitHub
- 2 unread notifications (PR review requested on aegis)

## Reading
- "Building distributed systems with Rust" (HN, 342 points)
```

### Graph topology (updated)

```
              init_run
                 |
     +-----------+-----------+-----------+-----------+
     v           v           v           v           v
 fetch_jobs  fetch_lc   fetch_github  fetch_hn  fetch_interviews
     |           |           |           |           |
     +-----------+-----------+-----------+-----------+
                 v
           check_fetches
            /         \
   all fail           >=1 succeeded
      |                    |
      v                    v
 degraded_output       prioritize
      |                    |
      |                    v
      |              synthesize
      |                    |
      |                    v
      |              self_evaluate
      |                    |
      |              maybe_refine
      |               /       \
      |        refine         ok
      |           |            |
      |           v            |
      |     (back to           |
      |      synthesize)       |
      |                        |
      +----------+-------------+
                 v
              persist
                 |
                 v
               END
```

## Project structure

```
aegis/
├── pyproject.toml
├── uv.lock
├── Dockerfile
├── docker-compose.yml
├── fly.toml
├── .env.example
├── README.md
├── AEGIS_PROJECT_PLAN.md
├── migrations/
│   ├── 001_initial.sql
│   └── 002_jobs_and_leetcode.sql
├── src/
│   └── aegis/
│       ├── __init__.py
│       ├── config.py
│       ├── logging.py
│       ├── app.py
│       ├── mcp_server.py
│       │
│       ├── db/
│       │   ├── engine.py
│       │   ├── repository.py         # BriefingRunRepository
│       │   ├── jobs_repository.py    # JobApplicationRepository
│       │   ├── leetcode_repository.py # LeetCodeRepository
│       │   └── cache.py
│       │
│       ├── llm/
│       │   ├── gateway.py
│       │   └── prompts.py
│       │
│       ├── sources/
│       │   ├── base.py
│       │   ├── github.py
│       │   ├── hn.py
│       │   ├── leetcode.py
│       │   ├── jobs_source.py        # reads from internal DB for briefing
│       │   └── leetcode_source.py    # reads from internal DB for briefing
│       │
│       ├── jobs/
│       │   ├── __init__.py
│       │   ├── analyzer.py           # LLM-powered JD parsing + fit scoring
│       │   └── service.py            # JobService (CRUD + analysis)
│       │
│       ├── leetcode/
│       │   ├── __init__.py
│       │   └── service.py            # LeetCodeService (CRUD + suggestions)
│       │
│       ├── briefing/
│       │   ├── service.py
│       │   ├── state.py
│       │   ├── nodes.py
│       │   └── graph.py
│       │
│       ├── scheduler/
│       │   └── apscheduler_runner.py
│       │
│       └── api/
│           ├── health.py
│           ├── briefing.py
│           └── jobs.py
│
└── tests/
    ├── conftest.py
    ├── unit/
    │   ├── test_sources_github.py
    │   ├── test_sources_hn.py
    │   ├── test_sources_leetcode.py
    │   ├── test_llm_gateway.py
    │   ├── test_job_analyzer.py
    │   └── test_leetcode_service.py
    ├── integration/
    │   ├── test_briefing_graph_e2e.py
    │   ├── test_mcp_server.py
    │   ├── test_jobs_repository.py
    │   └── test_api.py
    └── fixtures/
        └── sample_source_payloads/
```

## Configuration

```bash
# --- Core ---
AEGIS_ENV=local
LOG_LEVEL=INFO

# --- LLM ---
ANTHROPIC_API_KEY=sk-ant-...
AEGIS_LLM_MODEL=claude-sonnet-4-5
AEGIS_LLM_MAX_COST_USD_PER_RUN=0.50

# --- Profile ---
AEGIS_PROFILE_SKILLS=python,golang,distributed-systems,postgresql,redis,docker,kubernetes,fastapi,async-programming,system-design
AEGIS_PROFILE_TARGET_ROLES=backend-engineer,platform-engineer,ai-engineer
AEGIS_PROFILE_EXPERIENCE_YEARS=3
AEGIS_PROFILE_PREFERRED_LOCATIONS=singapore,remote
AEGIS_PROFILE_DEAL_BREAKERS=php,wordpress

# --- Data sources ---
GITHUB_TOKEN=ghp_...
GITHUB_USERNAME=narenarya3
LEETCODE_SESSION=

# --- Infrastructure ---
DATABASE_URL=postgresql://aegis:aegis@localhost:5432/aegis
REDIS_URL=redis://localhost:6379/0

# --- Scheduler ---
AEGIS_BRIEFING_CRON=0 7 * * *
AEGIS_TIMEZONE=Asia/Singapore
```

## Build plan

### Phase 1 -- Skeleton (done)

- [x] `pyproject.toml` with deps
- [x] `config.py`, `logging.py`, `db/engine.py`, `db/repository.py`, `db/cache.py`
- [x] SQL migration (briefing_runs + briefing_latest)
- [x] `docker-compose.yml` with Postgres + Redis
- [x] FastAPI app factory + `/health` endpoint
- [x] `sources/base.py`, `briefing/state.py`, `scheduler/apscheduler_runner.py`

### Phase 2 -- Source clients (done)

- [x] `sources/github.py`, `sources/hn.py`, `sources/leetcode.py`
- [x] Unit tests with recorded fixtures (9 tests passing)

### Phase 3 -- LLM gateway (done)

- [x] `llm/gateway.py` with cost tracking and budget cap
- [x] `llm/prompts.py` with prioritize/synthesize/evaluate templates
- [x] Unit tests (4 tests passing)

### Phase 4a -- Job tracker (current)

- [ ] `migrations/002_jobs_and_leetcode.sql` -- job_applications + leetcode_problems tables
- [ ] `db/jobs_repository.py` -- CRUD for job applications
- [ ] `jobs/analyzer.py` -- LLM-powered JD parsing, fit scoring, gap analysis
- [ ] `jobs/service.py` -- JobService coordinating repository + analyzer
- [ ] Update `config.py` with profile settings
- [ ] Unit tests for analyzer, integration tests for repository

### Phase 4b -- LeetCode tracker

- [ ] `db/leetcode_repository.py` -- CRUD for leetcode problems
- [ ] `leetcode/service.py` -- LeetCodeService with progress stats and next-problem suggestions
- [ ] Unit tests

### Phase 4c -- Briefing agent (LangGraph)

- [ ] Update `briefing/state.py` with job/leetcode data fields
- [ ] `sources/jobs_source.py` + `sources/leetcode_source.py` -- internal DB sources for briefing
- [ ] `briefing/nodes.py` -- all nodes including new data sources
- [ ] `briefing/graph.py` -- assemble graph with fan-out across 5 sources
- [ ] `briefing/service.py` -- BriefingService entry point
- [ ] Update `llm/prompts.py` with career-focused prompt templates
- [ ] Integration test with mocked sources and LLM

### Phase 5 -- MCP server + API

- [ ] `mcp_server.py` -- all tools/resources/prompts wired to services
- [ ] `api/jobs.py` -- REST endpoints for job tracker
- [ ] `api/briefing.py` -- wire to BriefingService
- [ ] `scheduler/apscheduler_runner.py` -- wire to briefing cron
- [ ] Manual test from Claude Desktop

### Phase 6 -- Interview prep agent (v0.2)

- [ ] `migrations/003_interview_sessions.sql`
- [ ] `interview/service.py` -- mock questions, answer evaluation, readiness scoring
- [ ] MCP tools for interview prep
- [ ] Integration with job tracker (company-specific prep)

### Phase 7 -- Deployment

- [ ] `Dockerfile` (multi-stage)
- [ ] `fly.toml` + Fly.io deployment
- [ ] Smoke test in prod

## Coding conventions

- **Types**: everything is type-annotated
- **Async everywhere**: `httpx.AsyncClient`, `asyncpg`, `redis.asyncio`
- **Errors**: sources and LLM calls return result objects, never raise for expected failures
- **Logging**: Loguru with `run_id` bound when inside a run
- **Tests**: integration tests with testcontainers, mock only the network boundary
- **No secrets in code.** All config via env
- **Commit style**: conventional commits

## Key design principles

1. **MCP-first**: Every capability is exposed through MCP tools/resources.
2. **Your data first**: Briefing prioritizes internal data (jobs, LeetCode, interviews) over external feeds.
3. **Fail-open**: Agents always produce output, even if degraded.
4. **Cost-aware**: Track tokens and cost per run. Budget caps enforced.
5. **Testable**: Every node is a pure function. Mock only external boundaries.
6. **Career-focused**: Every feature should directly help you get hired or improve your skills.

## Resume bullet (target)

"Designed and built Aegis, an MCP-native career growth platform using Python, LangGraph, and FastMCP. Features include LLM-powered job fit scoring with gap analysis, LeetCode progress tracking with pattern-based recommendations, and a daily briefing agent that orchestrates parallel data fetching with self-evaluation refinement loops, fail-open resilience, and per-run cost tracking. Exposed as MCP tools for interoperability with Claude Desktop, Claude Code, and Cursor."
