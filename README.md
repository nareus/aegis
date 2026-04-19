# Aegis

Personal agent platform for SWE career growth. Tracks job applications, LeetCode progress, and interview prep — exposed as MCP tools so Claude Desktop and Claude Code can act on them directly.

## What it does

- **Job Tracker** — paste a LinkedIn JD, get a fit score against your profile, track application status and follow-ups
- **LeetCode Tracker** — log problems by pattern, see weak areas, get AI-suggested next problems
- **Interview Prep** — generate mock system design and behavioral questions, submit answers for LLM evaluation, track readiness per company
- **Daily Briefing** — AI-generated morning summary pulling from all three trackers plus GitHub and HN

## Quick start

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (for postgres + redis)
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)

### First-time setup

```bash
git clone https://github.com/narenarya3/aegis
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
LEETCODE_SESSION=...             # optional: auto-sync AC submissions
LEETCODE_USERNAME=your-username  # optional: pair with LEETCODE_SESSION
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
In Claude: *"Run my daily briefing"* → triggers `run_briefing`, returns a prioritised summary of your day.

### Adding a job
1. Copy a LinkedIn JD (or any job posting text)
2. In Claude: *"Add this job: [paste JD]"*
3. Aegis parses it, scores fit against your profile, saves it

Or via API:
```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"text": "Senior Backend Engineer at Stripe...", "url": "https://linkedin.com/jobs/..."}'
```

### LeetCode tracking
In Claude:
- *"I just solved Two Sum — log it as arrays, hash-table, Easy"*
- *"What should I practice next?"*
- *"Show my LeetCode progress"*

### Interview prep
In Claude:
- *"Give me a system design question for Stripe"*
- *"Here's my answer: [paste answer]"* → get scored feedback
- *"How ready am I for my Stripe interview?"*

## All commands

| Command | What it does |
|---|---|
| `make start` | First-time setup: install, start infra, migrate |
| `make api` | Start REST API at http://localhost:8000 |
| `make mcp` | Start MCP server for Claude |
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

Edit `.env` to tune fit scoring and interview prep to your background:

```bash
AEGIS_PROFILE_SKILLS=python,golang,distributed-systems,postgresql,redis,docker,kubernetes
AEGIS_PROFILE_TARGET_ROLES=backend-engineer,platform-engineer,ai-engineer
AEGIS_PROFILE_EXPERIENCE_YEARS=3
AEGIS_PROFILE_PREFERRED_LOCATIONS=singapore,remote
AEGIS_PROFILE_DEAL_BREAKERS=php,wordpress
```

## Project structure

```
aegis/
├── src/aegis/
│   ├── briefing/        # LangGraph daily briefing agent
│   ├── interview/       # Interview prep service
│   ├── jobs/            # Job tracker + LLM fit scoring
│   ├── leetcode/        # LeetCode progress tracker
│   ├── db/              # asyncpg repositories
│   ├── llm/             # Anthropic gateway + prompts
│   ├── sources/         # GitHub, HN, LeetCode, internal DB sources
│   ├── api/             # FastAPI routers
│   ├── scheduler/       # APScheduler cron runner
│   ├── app.py           # FastAPI factory
│   └── mcp_server.py    # FastMCP server (all tools/resources/prompts)
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

79 tests, no external dependencies required (all network calls are mocked).
