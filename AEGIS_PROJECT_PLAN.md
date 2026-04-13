# Aegis -- MCP-Native Agentic Platform for SWE Workflows

## Project overview

Aegis is a personal agent platform that exposes SWE-specific autonomous agents as MCP (Model Context Protocol) tools, resources, and prompts. Any MCP client (Claude Code, Cursor, Claude Desktop, or a custom Telegram bot) can interact with the agents. The platform uses LangGraph for agent orchestration with durable checkpointing, parallel execution, and self-evaluation loops.

The first agent is the **Daily Briefing Agent**, which aggregates data from GitHub, LeetCode, Hacker News, and a job application tracker, then uses LLM-driven prioritization and synthesis to deliver a personalized daily briefing.

## Tech stack

- **Language**: Python 3.12+, `uv` for package management
- **Agent framework**: LangGraph (stateful graph-based agent orchestration)
- **MCP server**: FastMCP (Python MCP SDK) with stdio transport for Claude Desktop/Code
- **LLM provider**: Anthropic Claude API (direct SDK, no LangChain wrappers)
- **API layer**: FastAPI (health checks, manual triggers, cron target)
- **State persistence**: PostgreSQL 16 (briefing runs, job tracker, LangGraph checkpoints)
- **Caching**: Redis 7 (API response caching, rate limit tracking)
- **Scheduling**: APScheduler (cron-triggered agent runs)
- **Delivery**: Telegram Bot API (v0.2 -- thin MCP client that calls Aegis server)
- **Testing**: pytest + pytest-asyncio + testcontainers-python (Postgres, Redis)
- **Logging**: Loguru (JSON output in prod, human-readable locally)
- **Database access**: Raw asyncpg with numbered SQL migrations
- **Infrastructure**: Docker Compose (local dev), Fly.io (production)

## Architecture

### Layer 1: MCP server (the public interface)

Aegis exposes all functionality through MCP primitives. This is the only external interface.

**Tools** (actions clients can invoke):
- `run_briefing()` -- Trigger a fresh daily briefing run, returns run_id and status
- `get_latest_briefing()` -- Return the most recent successful briefing (markdown + metadata)
- `get_briefing_run(run_id)` -- Fetch a specific past run by ID
- `list_recent_runs(limit)` -- List recent runs with run_id, timestamp, quality_score, cost
- `add_job_application(company, role, url, status)` -- Track a new job application (v0.2)
- `update_job_status(app_id, new_status, notes)` -- Update an application status (v0.2)
- `get_follow_up_reminders()` -- List applications that need follow-up (v0.2)
- `get_agent_status()` -- Health check for all registered agents (v0.2)

**Resources** (read-only data):
- `briefing://latest` -- Most recent briefing as markdown
- `briefing://run/{run_id}` -- Specific run as markdown
- `aegis://jobs/dashboard` -- Job application statuses (v0.2)
- `aegis://jobs/reminders` -- Stale applications needing follow-up (v0.2)
- `aegis://agents/runs` -- Recent agent run history with costs (v0.2)

**Prompts** (reusable templates):
- `morning_standup()` -- "Give me my daily briefing and tell me what to focus on first."
- `system_design_question(topic, level)` -- Generate a system design question (v0.2)
- `resume_bullet_review(bullet)` -- Critique a resume bullet (v0.2)

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

Each agent is a LangGraph StateGraph. The platform provides shared infrastructure:

- **BriefingService**: Single entry point for all trigger paths (MCP, API, scheduler)
- **Scheduler**: APScheduler runs agents on cron schedules with timezone support
- **LangGraph checkpointing**: PostgreSQL-backed `AsyncPostgresSaver` for durable execution
- **Source clients**: Manage external API auth, caching (Redis), rate limits, and retry logic
- **LLM Gateway**: Direct Anthropic SDK wrapper with cost tracking and budget caps

### Layer 3: Infrastructure

- PostgreSQL 16: Briefing runs, LangGraph checkpoints, job tracker (v0.2)
- Redis 7: API response caching (GitHub, HN), rate limit counters
- Docker Compose: One-command local setup
- Fly.io: Production deployment (app + Postgres + Upstash Redis)

## Daily Briefing Agent -- detailed design

### State schema

```python
from typing import TypedDict

class BriefingState(TypedDict):
    run_id: str
    triggered_at: str
    trigger_source: str                  # "cron" | "mcp" | "api"

    # Raw fetched data, keyed by source name
    raw: dict[str, dict | None]          # {"github": {...}, "hn": [...], "leetcode": {...}}
    fetch_errors: dict[str, str]         # {"leetcode": "429 rate limit"}

    # LLM outputs
    prioritized: dict | None
    briefing_markdown: str | None
    quality_score: float | None
    iterations: int

    # Bookkeeping
    total_cost_usd: float
    total_latency_ms: int
```

### Graph topology

```
              init_run
                 |
     +-----------+-----------+
     v           v           v
 fetch_github fetch_hn  fetch_leetcode
     |           |           |
     +-----------+-----------+
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

### Nodes

| Node | Purpose | Can fail? |
|---|---|---|
| `init_run` | Assign `run_id`, write initial row to `briefing_runs` table | No (hard fail = abort) |
| `fetch_github` | Fetch user's starred/trending + notifications via GitHub REST | Yes (fail-open) |
| `fetch_hn` | Fetch top stories from HN Firebase API | Yes (fail-open) |
| `fetch_leetcode` | Fetch daily challenge via LeetCode GraphQL | Yes (fail-open) |
| `check_fetches` | Conditional: all failed -> `degraded_output`; else -> `prioritize` | No |
| `prioritize` | LLM call: rank and tag items by relevance | Yes (retry once, then degraded) |
| `synthesize` | LLM call: write final markdown briefing | Yes (retry once) |
| `self_evaluate` | LLM call: score own output 0-1 on "useful + concise + accurate" | Yes (default score = 0.7) |
| `maybe_refine` | Conditional: if score < 0.7 and `iterations < 2`, loop back to `synthesize` | No |
| `degraded_output` | Emit a minimal briefing listing what failed + any raw items we did get | No |
| `persist` | Write final state to `briefing_runs`, update `briefing_latest` pointer | No |

### Node implementations

**fetch_github**: Call GitHub REST API for:
- Recent commits on your repos (last 24h)
- Open PRs requiring your review
- PR review requests from others
- Repository activity on starred repos

**fetch_leetcode**: Call LeetCode GraphQL API for:
- Daily challenge problem
- Current streak status (if LEETCODE_SESSION configured)

**fetch_hn**: Call HN Algolia API for:
- Top stories filtered by keywords: "distributed systems", "AI infrastructure", "system design", etc.
- Apply relevance scoring based on interests

**prioritize (LLM call)**:
- System prompt includes current goals and priorities
- Input: all fetched data
- Output: ranked list of items with priority scores and reasoning
- Time-sensitive items get boosted

**synthesize (LLM call)**:
- Takes prioritized items and generates a structured briefing
- Format: sections for "Action required", "Updates", "Reading", "Stats"
- Concise, scannable, references specific data points

**self_evaluate (LLM call)**:
- Scores on: relevance, actionability, conciseness
- Returns score 0.0-1.0 and specific feedback
- If score < 0.7, feedback is passed back to synthesize for refinement
- Max 2 refinement iterations

### Fail-open resilience

Each fetch node wraps its API call in a try/except. On failure, the node returns successfully with error metadata rather than crashing the graph. The briefing agent always produces output, even if degraded.

### Checkpointing

`AsyncPostgresSaver` bound to the same Postgres instance. Thread ID = `run_id`. Every node boundary writes a checkpoint, giving free resumability and an audit trail of node-level state.

## FastAPI surface

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness + DB/Redis ping |
| `POST` | `/briefing/run` | Trigger a run (returns `run_id` immediately, runs in background) |
| `GET` | `/briefing/latest` | Latest briefing as JSON |
| `GET` | `/briefing/runs/{run_id}` | Specific run |
| `GET` | `/briefing/runs` | Paginated list |

## Database schema

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

### job_applications (v0.2)
```sql
CREATE TABLE job_applications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company TEXT NOT NULL,
    role TEXT NOT NULL,
    url TEXT,
    status TEXT NOT NULL DEFAULT 'applied',
    applied_date TIMESTAMP DEFAULT NOW(),
    last_activity TIMESTAMP DEFAULT NOW(),
    notes TEXT,
    priority TEXT DEFAULT 'medium',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

LangGraph checkpointer owns its own tables (`checkpoints`, `checkpoint_writes`, `checkpoint_blobs`) via `AsyncPostgresSaver.setup()`.

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
│   └── 001_initial.sql
├── src/
│   └── aegis/
│       ├── __init__.py
│       ├── config.py              # Pydantic Settings (env vars)
│       ├── logging.py             # Loguru setup + cost estimation
│       ├── app.py                 # FastAPI app factory
│       ├── mcp_server.py          # FastMCP entrypoint (python -m aegis.mcp_server)
│       │
│       ├── db/
│       │   ├── __init__.py
│       │   ├── engine.py          # asyncpg pool management
│       │   ├── repository.py      # BriefingRunRepository
│       │   └── cache.py           # Redis caching wrapper
│       │
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── gateway.py         # LLMGateway: direct Anthropic SDK, cost tracking
│       │   └── prompts.py         # Prompt templates (prioritize, synthesize, eval)
│       │
│       ├── sources/
│       │   ├── __init__.py
│       │   ├── base.py            # Source protocol + SourceResult type
│       │   ├── github.py
│       │   ├── hn.py
│       │   └── leetcode.py
│       │
│       ├── briefing/
│       │   ├── __init__.py
│       │   ├── service.py         # BriefingService (single entry point)
│       │   ├── state.py           # BriefingState TypedDict
│       │   ├── nodes.py           # LangGraph node functions
│       │   └── graph.py           # build_briefing_graph()
│       │
│       ├── scheduler/
│       │   ├── __init__.py
│       │   └── apscheduler_runner.py
│       │
│       └── api/
│           ├── __init__.py
│           ├── health.py
│           └── briefing.py
│
└── tests/
    ├── conftest.py
    ├── unit/
    │   ├── test_sources_github.py
    │   ├── test_sources_hn.py
    │   ├── test_sources_leetcode.py
    │   ├── test_nodes.py
    │   └── test_llm_gateway.py
    ├── integration/
    │   ├── test_briefing_graph_e2e.py
    │   ├── test_mcp_server.py
    │   └── test_api.py
    └── fixtures/
        └── sample_source_payloads/
```

## Configuration

All config via environment variables, loaded through `pydantic-settings`:

```bash
# --- Core ---
AEGIS_ENV=local                          # local | prod
LOG_LEVEL=INFO

# --- LLM ---
ANTHROPIC_API_KEY=sk-ant-...
AEGIS_LLM_MODEL=claude-sonnet-4-5
AEGIS_LLM_MAX_COST_USD_PER_RUN=0.50

# --- Data sources ---
GITHUB_TOKEN=ghp_...
GITHUB_USERNAME=narenarya3
LEETCODE_SESSION=                        # optional, for personalized data

# --- Infrastructure ---
DATABASE_URL=postgresql://aegis:aegis@localhost:5432/aegis
REDIS_URL=redis://localhost:6379/0

# --- Scheduler ---
AEGIS_BRIEFING_CRON=0 7 * * *
AEGIS_TIMEZONE=Asia/Singapore
```

## Build plan

### Phase 1 -- Skeleton (done)

- [x] `uv init`, set up `pyproject.toml` with deps (loguru, anthropic, langgraph, fastapi, asyncpg, redis, apscheduler, mcp, httpx)
- [x] `config.py`, `logging.py`, `db/engine.py`, `db/repository.py`, `db/cache.py`
- [x] SQL migration (briefing_runs + briefing_latest)
- [x] `docker-compose.yml` with Postgres + Redis
- [x] FastAPI app factory + `/health` endpoint
- [x] `sources/base.py` (Source protocol + SourceResult)
- [x] `briefing/state.py` (BriefingState TypedDict)
- [x] `scheduler/apscheduler_runner.py`
- [x] Stub MCP server and API routes

### Phase 2 -- Source clients

- [ ] `sources/github.py`: fetch notifications, starred repos, recent activity via GitHub REST API
- [ ] `sources/hn.py`: fetch top stories from HN Firebase API, filter by keywords
- [ ] `sources/leetcode.py`: fetch daily challenge via LeetCode GraphQL
- [ ] Unit tests with recorded fixtures (no live network in unit tests)

### Phase 3 -- LLM gateway

- [ ] `llm/gateway.py`: direct Anthropic SDK wrapper, `call()` method, cost tracking, budget cap
- [ ] `llm/prompts.py`: three prompt templates (prioritize, synthesize, self-evaluate)
- [ ] Unit test with a mock Anthropic client

### Phase 4 -- LangGraph briefing agent

- [ ] `briefing/nodes.py`: implement all nodes as pure async functions
- [ ] `briefing/graph.py`: assemble graph, wire `AsyncPostgresSaver`, export `build_briefing_graph()`
- [ ] `briefing/service.py`: `BriefingService.run(trigger_source)` kicks off the graph
- [ ] Integration test: full graph against testcontainers with mocked sources and mocked LLM

### Phase 5 -- Interfaces

- [ ] `api/briefing.py`: wire FastAPI routes to BriefingService
- [ ] `mcp_server.py`: FastMCP tools/resources/prompts, all delegating to BriefingService
- [ ] `scheduler/apscheduler_runner.py`: wire to `BriefingService.run("cron")`
- [ ] Manual test: trigger via curl, via MCP (Claude Desktop), via scheduler

### Phase 6 -- Deployment

- [ ] `Dockerfile` (multi-stage: uv build -> slim runtime)
- [ ] `fly.toml` + `fly launch`
- [ ] Fly Postgres + Upstash Redis provisioning
- [ ] Smoke test in prod

### Phase 7 -- v0.2 (future)

- [ ] Job application tracker (DB table + MCP tools + MCP resources)
- [ ] Telegram bot delivery
- [ ] LangSmith tracing
- [ ] OpenAI fallback in LLM gateway
- [ ] Additional MCP prompts (system design, resume review)
- [ ] Multiple agents / agent registry

## Coding conventions

- **Types**: everything is type-annotated
- **Async everywhere**: no blocking calls inside async functions. Use `httpx.AsyncClient`, `asyncpg`, `redis.asyncio`
- **Errors**: sources and LLM calls return result objects, never raise for expected failures. Raise only for programmer errors
- **Logging**: Loguru with `run_id` bound when inside a run. JSON in prod, human-readable locally
- **Tests**: prefer integration tests with testcontainers over heavy mocking. Mock only the network boundary
- **No secrets in code.** All config via env
- **Commit style**: conventional commits (`feat:`, `fix:`, `chore:`, etc.)

## Key design principles

1. **MCP-first**: Every capability is exposed through MCP. No backdoor APIs.
2. **Fail-open**: Agents always produce output, even if degraded. Partial data is better than no data.
3. **Cost-aware**: Track tokens and estimated cost per agent run. Set budget limits.
4. **Testable**: Every node is a pure function that takes state and returns state.
5. **Incremental**: The platform supports N agents, but ship with 1.

## Resume bullet (target)

"Designed and built Aegis, an MCP-native agentic platform for SWE workflows using Python, LangGraph, and FastMCP. Exposes domain-specific agents as MCP tools/resources/prompts for interoperability with Claude Code, Cursor, and any MCP client. The Daily Briefing Agent orchestrates parallel data fetching across 3 sources, applies LLM-driven prioritization with a self-evaluation refinement loop, and delivers personalized briefings with fail-open resilience, durable checkpointing, and per-run cost tracking."

## Future agents (post-MVP)

- **Interview Prep Agent**: Conducts adaptive mock interviews, tracks weak areas across sessions
- **Job Search Agent**: Monitors job boards, matches postings to your profile, drafts tailored applications
- **Code Review Agent**: Analyzes GitHub PRs across dimensions (correctness, performance, security)
