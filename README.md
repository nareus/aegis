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

**Inspect anything** — every LLM call emits a span. Run `aegis api` and
open `http://localhost:8000/trace/<run_id>` for a tree of every prompt,
response, cost, and latency, or pull the JSON at `/trace/<run_id>/json`.

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
- **FastAPI surface** (`src/aegis/app.py`, `src/aegis/api/`) — REST routers
  for jobs, briefing, traces, health. Exposed via `aegis api`. Health check
  returns 503 when degraded.

---

## Quick start

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) — Aegis runs Postgres + Redis locally.
- [uv](https://docs.astral.sh/uv/getting-started/installation/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Anthropic API key** — required. Generate at <https://console.anthropic.com/settings/keys>.
- **GitHub personal access token** — optional, only for the daily briefing.
  Generate at <https://github.com/settings/tokens>. Classic token needs the
  `notifications` scope; fine-grained needs `Notifications: Read`. Without
  it, briefings still run but skip the GitHub section.

### Install

```bash
uv tool install aegis-agents
aegis init          # prompts for ANTHROPIC_API_KEY + GITHUB_TOKEN (optional)
aegis up            # boots Postgres + Redis, applies migrations
```

`aegis init` writes `~/.config/aegis/{.env,compose.yml,profile.yaml}`. Re-run
with `--force` to regenerate. Override the location with `AEGIS_HOME=/path`.

Edit `~/.config/aegis/profile.yaml` to personalise fit scoring (skills, target
roles, deal-breakers).

### Wire to Claude

**Claude Code:**

```bash
claude mcp add aegis -- aegis serve
```

**Claude Desktop** — add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "aegis": {
      "command": "aegis",
      "args": ["serve"]
    }
  }
}
```

Restart Claude. The `aegis` tools show up under the connector menu.

### Daily ops

| Command | What it does |
|---|---|
| `aegis up` | Start Postgres + Redis (data preserved across restarts) |
| `aegis down` | Stop the stack |
| `aegis migrate` | Apply new migrations after an `aegis-agents` upgrade |
| `aegis doctor` | Diagnose prerequisites, config, and infra |
| `aegis serve` | Run the MCP server (what Claude calls) |
| `aegis api` | Run the REST API + trace viewer at <http://localhost:8000/docs> |
| `aegis init --force` | Regenerate `~/.config/aegis/` files |

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

Or curl (requires `aegis api` running):
```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"text": "Senior Backend Engineer at Stripe..."}'
```

### Inspecting a run
- *"List my recent Aegis runs"* in Claude → `list_recent_runs` shows
  newest-first runs with `run_id` and trace links.
- *"Get the trace for `<run_id>`"* → flat span summary.
- With `aegis api` running, `http://localhost:8000/trace/<run_id>` →
  full HTML tree with every prompt and response.

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

The eval harness is maintainer tooling — it ships in the repo, not the
package. Clone the repo and run:

```bash
uv run python scripts/seed_evals.py             # mirror evals/*/cases/*.yaml → eval_golden_cases
uv run python scripts/run_eval.py job_fit_v1    # run the suite
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

## Profile configuration

`aegis init` writes `~/.config/aegis/profile.yaml` from the bundled
template. Edit it to personalise fit-scoring and briefing output:

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

Set `AEGIS_PROFILE_PATH=/some/other/path.yaml` to point Aegis at a
profile outside the default location.

---

## Tuning

| Env var | Default | Purpose |
|---|---|---|
| `AEGIS_LLM_MODEL` | `claude-sonnet-4-5` | Anthropic model for every agent |
| `AEGIS_LLM_MAX_COST_USD_PER_RUN` | `0.50` | Hard cap per gateway instance |
| `AEGIS_LLM_MAX_COST_USD_PER_DAY` | `5.0` | Aggregate cap across the last 24h (0 disables) |
| `AEGIS_MAX_REFINEMENTS` | `2` | Max critic ⇄ analyst loops |
| `AEGIS_PROFILE_PATH` | `~/.config/aegis/profile.yaml` | Where the candidate profile lives |
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
└── pyproject.toml
```

---

## Development

Working on Aegis itself (rather than using it):

```bash
git clone https://github.com/nareus/aegis
cd aegis
uv sync                                # install deps + dev tools
aegis init                             # one-time, sets up ~/.config/aegis/
aegis up                               # start Postgres + Redis

uv run python -m aegis.cli serve       # run MCP server from source
uv run pytest                          # full suite, all network mocked
uv run pytest tests/unit/              # fast, no Docker
uv run pytest tests/integration/ -v    # spins up Postgres via testcontainers

uv run python scripts/seed_evals.py    # mirror eval cases to Postgres
uv run python scripts/run_eval.py job_fit_v1
```

`scripts/` and `evals/` ship in the repo for regression testing and aren't
bundled into the published package.

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

These are intentional cuts for a local-first tool.

---

## License

MIT. Fork it, rewire it, ship it.
