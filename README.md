# Aegis

Personal agent platform for SWE career growth. Tracks job applications and produces a daily briefing — exposed as MCP tools so Claude Desktop and Claude Code can act on them directly.

## What it does

- **Job Tracker** — paste a JD (text or URL), a multi-agent pipeline (Researcher → Analyst → Critic with a refinement loop) extracts the role, scores fit against your profile, and persists the result with full trace metadata.
- **Daily Briefing** — LangGraph agent that fans out to GitHub, Hacker News, and your own job pipeline, prioritises items, synthesises a markdown briefing, then self-evaluates and refines if quality is low.
- **Tracing viewer** — every workflow run gets a `run_id`; visit `/trace/{run_id}` for an HTML span tree with per-node cost, tokens, and latency.

## Quick start

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (for postgres + redis)
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)

### First-time setup

```bash
git clone https://github.com/nareus/aegis
cd aegis
make start
```

`make start` will:
1. Copy `.env.example` → `.env`
2. Install Python dependencies
3. Start postgres and redis in Docker
4. Apply all database migrations

Then open `.env` and fill in your API keys:

```bash
ANTHROPIC_API_KEY=sk-ant-...     # required for all LLM features
GITHUB_TOKEN=ghp_...             # required for GitHub briefing section
GITHUB_USERNAME=your-handle      # GitHub user the briefing reads from
```

### Run the API

```bash
make api
```

Open **http://localhost:8000/docs** — interactive API docs where you can test every endpoint directly in the browser.

### Use from Claude (MCP)

```bash
make mcp
```

Or configure it to start automatically. Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "aegis": {
      "command": "uv",
      "args": ["--directory", "/path/to/aegis", "run", "aegis"],
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-...",
        "DATABASE_URL": "postgresql://aegis:aegis@localhost:5432/aegis",
        "REDIS_URL": "redis://localhost:6379/0",
        "GITHUB_TOKEN": "ghp_..."
      }
    }
  }
}
```

For Claude Code, run `claude mcp add` or add to your project's `.mcp.json`.

## Daily workflow

### Morning briefing
In Claude: *"Run my daily briefing"* → triggers `run_briefing`, returns a prioritised markdown summary plus a `trace_url` you can open to inspect every LLM call. The briefing is on-demand only — there's no background scheduler, so nothing runs unless you (or Claude) call it.

### Adding a job
1. Copy a LinkedIn JD (or any job posting text), or grab the URL.
2. In Claude: *"Add this job: [paste JD or URL]"*
3. Aegis runs Researcher → Analyst → Critic. If the critic flags issues, the analyst re-runs with that feedback (up to `AEGIS_MAX_REFINEMENTS` rounds), then persists the final analysis with `fit_score`, `recommendation`, refinement count, and the run's trace pointer.

Or via API:
```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"text": "Senior Backend Engineer at Stripe...", "url": "https://linkedin.com/jobs/..."}'
```

### Inspecting a run
- `get_trace(run_id)` from Claude returns a flat span summary.
- `http://localhost:8000/trace/{run_id}` renders the same data as a span tree in the browser; `/trace/{run_id}/json` gives the raw payload.

## MCP surface

**Tools:** `run_briefing`, `get_latest_briefing`, `add_job`, `list_jobs`, `update_job_status`, `get_follow_ups`, `get_top_job_fits`, `get_trace`.
**Resources:** `aegis://briefing/latest`, `aegis://jobs/summary`.
**Prompts:** `daily_briefing_prompt`.

## All commands

| Command | What it does |
|---|---|
| `make start` | First-time setup: install, start infra, migrate |
| `make api` | Start REST API at http://localhost:8000 |
| `make mcp` | Start MCP server for Claude |
| `make doctor` | Check prerequisites and config |
| `make stop` | Stop postgres + redis (data preserved) |
| `make restart` | Restart infra |
| `make migrate` | Apply new SQL migrations |
| `make logs` | Tail postgres + redis logs |
| `make reset` | ⚠ Wipe all data and start fresh |

## Data persistence

Your data lives in Docker named volumes (`aegis_postgres_data`, `aegis_redis_data`). It survives:
- `make stop` / `make start`
- Machine reboots
- Docker Desktop restarts

The only thing that wipes it is `make reset` (which asks for confirmation).

## Profile configuration

Edit `profile.yaml` (copied from `profile.example.yaml`) to tune fit scoring to your background:

```yaml
skills:
  - python
  - golang
  - distributed-systems
target_roles:
  - backend-engineer
  - ai-engineer
experience_years: 3
preferred_locations:
  - singapore
  - remote
deal_breakers:
  - php
  - wordpress
```

Point `AEGIS_PROFILE_PATH` at a different file if you want to keep the profile outside the repo.

## Tuning

| Env var | Default | Purpose |
|---|---|---|
| `AEGIS_LLM_MODEL` | `claude-sonnet-4-5` | Anthropic model used by every agent |
| `AEGIS_LLM_MAX_COST_USD_PER_RUN` | `0.50` | Hard budget per gateway instance — raises `BudgetExceededError` |
| `AEGIS_MAX_REFINEMENTS` | `2` | Max critic→analyst loops before the job analysis finalises |

## Project structure

```
aegis/
├── src/aegis/
│   ├── agents/          # Researcher, Analyst, Critic + auto-tracing base class
│   ├── workflows/
│   │   └── job_analysis/  # LangGraph wiring + service for the job-analysis pipeline
│   ├── briefing/        # LangGraph daily briefing agent (nodes, graph, service)
│   ├── jobs/            # Job service facade exposed by API and MCP
│   ├── sources/         # GitHub, HN, internal jobs source for the briefing
│   ├── llm/             # Anthropic gateway + prompts (cost-tracked, budget-capped)
│   ├── tracing/         # Span recorder, repository, HTML viewer
│   ├── db/              # asyncpg engine + repositories
│   ├── api/             # FastAPI routers (jobs, briefing, traces, health)
│   ├── app.py           # FastAPI factory
│   └── mcp_server.py    # FastMCP server (tools, resources, prompts)
├── migrations/          # Numbered SQL migrations (applied in order)
├── tests/
│   ├── unit/
│   └── integration/
├── Makefile
├── Dockerfile
├── docker-compose.yml
└── fly.toml             # Fly.io deployment (optional)
```

## Running tests

```bash
uv run pytest
```

All network calls are mocked, so the suite runs without API keys or live infra.
