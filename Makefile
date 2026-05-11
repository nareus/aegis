.PHONY: help start setup doctor api mcp stop restart migrate logs reset install eval seed-evals

# Default target
help:
	@echo ""
	@echo "  Aegis -- local development"
	@echo ""
	@echo "  make start      First-time setup: copy .env, install deps, start infra, migrate"
	@echo "  make doctor     Check all prerequisites and config (run this if something is broken)"
	@echo "  make api        Start the REST API  →  http://localhost:8000/docs"
	@echo "  make mcp        Start the MCP server (wire to Claude Desktop / Claude Code)"
	@echo "  make stop       Stop postgres + redis  (data is preserved)"
	@echo "  make restart    Restart infra"
	@echo "  make migrate    Apply any new SQL migrations"
	@echo "  make seed-evals Mirror evals/*/cases/*.yaml into eval_golden_cases"
	@echo "  make eval NAME=<eval_name>  Run an eval suite (e.g. NAME=job_fit_v1)"
	@echo "  make logs       Tail postgres + redis logs"
	@echo "  make reset      ⚠  Wipe ALL local data and start fresh"
	@echo ""

# ── First-time / daily start ────────────────────────────────────────────────

start: _copy_env install _infra_up migrate
	@echo ""
	@echo "  Aegis is ready."
	@echo "  Edit .env if you haven't added your API keys yet."
	@echo ""
	@echo "  make api    →  http://localhost:8000/docs"
	@echo "  make mcp    →  MCP server for Claude"
	@echo ""

# ── Diagnostics ─────────────────────────────────────────────────────────────

doctor:
	@echo ""
	@echo "  Checking prerequisites..."
	@command -v docker   >/dev/null 2>&1 && echo "  [ok] docker"     || echo "  [MISSING] docker -- https://docs.docker.com/get-docker/"
	@command -v uv       >/dev/null 2>&1 && echo "  [ok] uv"         || echo "  [MISSING] uv     -- curl -LsSf https://astral.sh/uv/install.sh | sh"
	@command -v psql     >/dev/null 2>&1 && echo "  [ok] psql"       || echo "  [optional] psql  -- brew install libpq && brew link --force libpq"
	@echo ""
	@echo "  Checking .env..."
	@if [ ! -f .env ]; then \
		echo "  [MISSING] .env not found -- run: cp .env.example .env"; \
	else \
		echo "  [ok] .env exists"; \
		grep -q "^ANTHROPIC_API_KEY=$$" .env 2>/dev/null \
			&& echo "  [MISSING] ANTHROPIC_API_KEY is empty -- edit .env" \
			|| (grep -q "^\.\.\." .env 2>/dev/null \
				&& echo "  [MISSING] ANTHROPIC_API_KEY is still a placeholder -- edit .env" \
				|| echo "  [ok] ANTHROPIC_API_KEY is set"); \
	fi
	@echo ""
	@echo "  Checking infrastructure..."
	@docker compose ps postgres 2>/dev/null | grep -q "running" \
		&& echo "  [ok] postgres is running" \
		|| echo "  [stopped] postgres -- run: make start"
	@docker compose ps redis 2>/dev/null | grep -q "running" \
		&& echo "  [ok] redis is running" \
		|| echo "  [stopped] redis    -- run: make start"
	@echo ""

# ── Individual commands ──────────────────────────────────────────────────────

install:
	uv sync

api:
	uv run uvicorn aegis.app:app --reload --host 0.0.0.0 --port 8000

mcp:
	uv run aegis

stop:
	docker compose stop postgres redis

restart: stop _infra_up

migrate:
	@for f in migrations/*.sql; do \
		echo "  Applying $$f..."; \
		psql "$(DATABASE_URL)" -f "$$f" 2>/dev/null || true; \
	done
	@echo "  Migrations done."

logs:
	docker compose logs -f postgres redis

seed-evals:
	uv run python scripts/seed_evals.py

eval:
	@if [ -z "$(NAME)" ]; then \
		echo "  Usage: make eval NAME=<eval_name>  (e.g. NAME=job_fit_v1)"; \
		exit 1; \
	fi
	uv run python scripts/run_eval.py $(NAME)

reset:
	@echo "⚠  This will DELETE all your data (jobs, briefings, traces)."
	@read -p "   Type 'yes' to continue: " confirm && [ "$$confirm" = "yes" ]
	docker compose down -v
	$(MAKE) _infra_up migrate
	@echo "  Reset complete."

# ── Internal ─────────────────────────────────────────────────────────────────

_infra_up:
	docker compose up postgres redis -d
	@echo "  Waiting for postgres..."
	@until docker compose exec postgres pg_isready -U aegis -q 2>/dev/null; do sleep 1; done
	@echo "  Postgres ready."

_copy_env:
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "  Copied .env.example → .env"; \
		echo "  Open .env and add your ANTHROPIC_API_KEY before using LLM features."; \
	fi
