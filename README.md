# Aegis

A local-first, MCP-native multi-agent platform you control. Aegis ships as a
working personal job-tracker + daily briefing for software engineers — but
the substrate underneath (agents, tracing, evals, MCP) is built to be lifted
into any domain where you want LLM workflows you can debug, eval, and budget.

> Built to be read, forked, and bent to your use case. Everything happens on
> your machine — your data, your API key, your prompts.

---

## What you can do today

**Out of the box** — two workflows wired end-to-end:

| Workflow | What it does | Trigger |
|---|---|---|
| **Job tracker** | Paste a JD (text or URL). A Researcher → Analyst → Critic pipeline extracts the role, scores fit against your `profile.yaml`, and loops if the critic flags issues. Persists with cost, refinement count, and a trace link. | `add_job` MCP tool, `POST /jobs`, or curl |
| **Daily briefing** | Fans out to GitHub (your activity + notifications), Hacker News, and your job pipeline. Prioritises items, synthesises a markdown briefing, then self-scores and refines. Falls open if a source fails. | `run_briefing` MCP tool, `POST /briefing/run`, or curl |

**Inspect anything** — every LLM call emits a span. Open
`http://localhost:8000/trace/<run_id>` for a tree of every prompt, response,
cost, and latency, or pull the JSON at `/trace/<run_id>/json`.

**Catch regressions** — YAML golden cases under `evals/<eval_name>/cases/*.yaml`
run through the real pipeline; the runner writes a row to `eval_runs` with
git SHA, score, and per-case detail.

**Budgets that bite** — per-run cap (`AEGIS_LLM_MAX_COST_USD_PER_RUN`) and
daily aggregate cap (`AEGIS_LLM_MAX_COST_USD_PER_DAY`) checked before every
LLM call. Tenacity retries handle transient Anthropic / Postgres failures.

---

## What's actually reusable — the building blocks

Aegis is small (~3k LOC). Pick what you need:

- **MCP server scaffold** (`src/aegis/mcp_server.py`) — FastMCP wiring with
  tools, resources, prompts, and a working Claude Desktop integration. Add a
  tool by writing one `@mcp.tool()` function.
- **Multi-agent framework** (`src/aegis/agents/`) — `AgentBase` gives every
  agent automatic tracing, cost attribution, and uniform `AgentResult`. Drop
  in a new agent by subclassing and writing `_run`.
- **LangGraph workflow pattern** (`src/aegis/workflows/job_analysis/graph.py`) —
  Researcher → Analyst → Critic with conditional refinement. Easy to copy and
  rewire into a different shape.
- **Tracing infra** (`src/aegis/tracing/`) — spans persisted to Postgres
  (`agent_traces` table) with a built-in HTML viewer. No Datadog needed.
- **Eval harness** (`scripts/run_eval.py`, `evals/*/cases/*.yaml`) — golden
  cases as YAML, assertion-based scoring (not exact-match), regression rows
  in `eval_runs`. Each case still produces a trace you can open.
- **LLM gateway** (`src/aegis/llm/gateway.py`) — Anthropic direct (no
  LangChain), with cost tracking, per-run + per-day budgets, retry on 5xx /
  timeouts / rate-limits.
- **FastAPI + Docker scaffolding** — health check (returns 503 when degraded
  so Fly/Kubernetes can react), multi-stage Dockerfile, docker-compose for
  local Postgres + Redis, Fly.toml for one-command cloud deploy.

---

## Quick start

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (for Postgres + Redis)
- [uv](https://docs.astral.sh/uv/getting-started/installation/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`

### First-time setup

```bash
git clone https://github.com/nareus/aegis
cd aegis
make start
```

`make start` copies `.env.example` → `.env`, installs deps, boots Postgres
and Redis in Docker, and runs every migration in order.

Then put your keys in `.env`:

```bash
ANTHROPIC_API_KEY=sk-ant-...     # required for all LLM features
GITHUB_TOKEN=ghp_...             # required for the briefing's GitHub section
GITHUB_USERNAME=your-handle      # who the briefing reads activity for
```

### Run the API

```bash
make api
```

Then open <http://localhost:8000/docs> — every endpoint is testable directly
in the browser, including `POST /jobs` and `POST /briefing/run`.

### Wire to Claude Desktop

Add this to `~/Library/Application Support/Claude/claude_desktop_config.json`:

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

Restart Claude Desktop. The `aegis` tools show up under the connector menu.

For Claude Code: `claude mcp add aegis -- uv --directory /path/to/aegis run aegis`.

---

## Daily workflow

### Morning briefing
In Claude: *"Run my daily briefing"* — fires `run_briefing`, returns
prioritised markdown with `trace_url`. There's no background scheduler;
briefings only fire when you (or Claude) ask.

### Adding a job
1. Copy a job posting (text or URL).
2. In Claude: *"Add this job: [paste]"* → `add_job` runs Researcher →
   Analyst → Critic, loops up to `AEGIS_MAX_REFINEMENTS` rounds if the
   critic flags issues, then persists.

Or curl:
```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"text": "Senior Backend Engineer at Stripe..."}'
```

### Inspecting a run
- *"List my recent Aegis runs"* in Claude → `list_recent_runs` shows
  newest-first runs with `run_id` and trace links.
- *"Get the trace for `<run_id>`"* → flat span summary.
- `http://localhost:8000/trace/<run_id>` → full HTML tree with every prompt
  and response.

---

## MCP surface

**Tools**

| Tool | What it does |
|---|---|
| `run_briefing` | Run a full briefing, return markdown + cost + trace pointer |
| `get_latest_briefing` | Most recent successful briefing |
| `add_job` | Run the multi-agent pipeline on a JD, persist + return analysis |
| `list_jobs` | List tracked jobs, optionally filtered by status |
| `update_job_status` | Move a job through the pipeline (saved → applied → …) |
| `get_follow_ups` | Stale-for-N-days jobs that need a nudge |
| `get_top_job_fits` | Saved jobs with `fit_score >= min_score` |
| `get_trace` | Span summary for a `run_id` |
| `list_recent_runs` | Newest-first run summaries with trace URLs |

**Resources**: `aegis://briefing/latest`, `aegis://jobs/summary`
**Prompts**: `daily_briefing_prompt`

---

## Evals — keep prompts honest

```bash
make seed-evals               # mirror evals/*/cases/*.yaml → eval_golden_cases
make eval NAME=job_fit_v1     # run the suite
```

Each YAML case declares assertions against the analysis (not exact-match
output, since LLMs aren't deterministic):

```yaml
case_id: stripe_senior_backend_apply
eval_name: job_fit_v1
input:
  url_or_text: |
    Senior Backend Engineer — Stripe (Remote, US) ...
expected:
  recommendation: apply
  fit_score: {min: 0.70, max: 1.00}
  must_include_skills: [python, postgresql]
  must_not_have_deal_breakers: true
```

The runner writes a row to `eval_runs` per invocation (git SHA, score,
pass count, per-case detail). Diff successive runs to track prompt
regressions.

When you hit a bad output in `agent_traces`, the recipe is: copy the JD
into a new case file with the correct `expected`, re-seed, re-run, fix the
prompt until it passes.

---

## All commands

| Command | What it does |
|---|---|
| `make start` | First-time setup |
| `make doctor` | Check prerequisites + config |
| `make api` | Start REST API |
| `make mcp` | Start MCP server (stdio) |
| `make seed-evals` | Mirror YAML golden cases into Postgres |
| `make eval NAME=…` | Run an eval suite end-to-end |
| `make migrate` | Apply new SQL migrations |
| `make stop` / `restart` | Stop / restart Docker infra (data preserved) |
| `make logs` | Tail Postgres + Redis logs |
| `make reset` | ⚠ Wipe ALL local data |

---

## Profile configuration

`profile.yaml` (copied from `profile.example.yaml`) drives fit-scoring and
briefing personalisation. It's git-ignored — the example is committed so
you can see the shape.

```yaml
skills: [python, golang, distributed-systems]
target_roles: [backend-engineer, ai-engineer]
experience_years: 3
preferred_locations: [singapore, remote]
deal_breakers: [php, wordpress]
summary: |
  Backend engineer with 3 years of experience building distributed
  systems in Python and Go. Interested in AI / agent platforms.
```

Point `AEGIS_PROFILE_PATH` at a different path to keep your profile outside
the repo.

---

## Tuning

| Env var | Default | Purpose |
|---|---|---|
| `AEGIS_LLM_MODEL` | `claude-sonnet-4-5` | Anthropic model for every agent |
| `AEGIS_LLM_MAX_COST_USD_PER_RUN` | `0.50` | Hard cap per gateway instance |
| `AEGIS_LLM_MAX_COST_USD_PER_DAY` | `5.0` | Aggregate cap across the last 24h (0 disables) |
| `AEGIS_MAX_REFINEMENTS` | `2` | Max critic ⇄ analyst loops |
| `AEGIS_PROFILE_PATH` | `./profile.yaml` | Where the candidate profile lives |
| `LOG_LEVEL` | `INFO` | Loguru level — `DEBUG` for verbose tracing |

---

## Project structure

```
aegis/
├── src/aegis/
│   ├── agents/          # Researcher, Analyst, Critic + auto-tracing base class
│   ├── workflows/
│   │   └── job_analysis/   # LangGraph wiring + service
│   ├── briefing/        # LangGraph daily-briefing nodes + graph + service
│   ├── jobs/            # Job service facade exposed by API and MCP
│   ├── sources/         # GitHub, HN, internal jobs source for the briefing
│   ├── llm/             # Anthropic gateway (cost-tracked, budget-capped, retrying)
│   ├── tracing/         # Span recorder + repository + HTML viewer
│   ├── db/              # asyncpg engine + repositories
│   ├── api/             # FastAPI routers (jobs, briefing, traces, health)
│   ├── app.py           # FastAPI factory
│   └── mcp_server.py    # FastMCP server (tools, resources, prompts)
├── migrations/          # Numbered SQL migrations
├── evals/               # YAML golden cases per eval_name
├── scripts/
│   ├── seed_evals.py    # YAML → eval_golden_cases
│   └── run_eval.py      # Run a suite, write eval_runs
├── tests/
│   ├── unit/            # Mocked LLM, no infra
│   └── integration/     # testcontainers, real Postgres
├── Makefile
├── Dockerfile           # Multi-stage, non-root user
├── docker-compose.yml
└── fly.toml             # Fly.io deploy (optional)
```

---

## Tests

```bash
uv run pytest                  # full suite, all network mocked
uv run pytest tests/unit/      # fast, no Docker
uv run pytest tests/integration/ -v   # spins up Postgres via testcontainers
```

---

## What's deliberately not here (yet)

So you know what you're signing up for:

- **No background scheduler** — briefings run only when triggered.
- **No auth on the FastAPI surface** — assume loopback / firewalled. Add an
  API-key middleware before exposing publicly.
- **No SSRF allow-list in the researcher fetch** — fine for trusted local
  use; restrict before exposing to untrusted JD URLs.
- **No LangGraph checkpointing** — a pod restart mid-workflow loses the run.
- **No multi-tenancy** — single profile, single user, single DB.

These are intentional cuts for a local-first tool. The "deployment gaps"
section in the engineering docs covers what changes if you want any of them.

---

## License

MIT. Fork it, rewire it, ship it.
