.PHONY: help test test-unit test-int eval seed-evals lint fmt build publish-test publish

# Default target — maintainer commands only. End users use the `aegis` CLI;
# see README for `aegis init`, `aegis up`, etc.

help:
	@echo ""
	@echo "  Aegis -- maintainer commands"
	@echo ""
	@echo "  make test                       Full pytest suite (network mocked)"
	@echo "  make test-unit                  Unit tests only (no Docker)"
	@echo "  make test-int                   Integration tests (testcontainers Postgres)"
	@echo ""
	@echo "  make eval NAME=<eval_name>      Run an eval suite (e.g. NAME=job_fit_v1)"
	@echo "  make seed-evals                 Mirror evals/*/cases/*.yaml to Postgres"
	@echo ""
	@echo "  make lint                       ruff check"
	@echo "  make fmt                        ruff format"
	@echo ""
	@echo "  make build                      Build wheel + sdist into dist/"
	@echo "  make publish-test               Publish to TestPyPI (needs UV_PUBLISH_TOKEN)"
	@echo "  make publish                    Publish to PyPI    (needs UV_PUBLISH_TOKEN, with confirm)"
	@echo ""
	@echo "  End users run 'aegis init', 'aegis up', etc. -- see README."
	@echo ""

# ── Tests ──────────────────────────────────────────────────────────────────────

test:
	uv run pytest

test-unit:
	uv run pytest tests/unit/

test-int:
	uv run pytest tests/integration/ -v

# ── Evals ──────────────────────────────────────────────────────────────────────

eval:
	@if [ -z "$(NAME)" ]; then \
		echo "  Usage: make eval NAME=<eval_name>  (e.g. NAME=job_fit_v1)"; \
		exit 1; \
	fi
	uv run python scripts/run_eval.py $(NAME)

seed-evals:
	uv run python scripts/seed_evals.py

# ── Lint / format ──────────────────────────────────────────────────────────────

lint:
	uv run ruff check .

fmt:
	uv run ruff format .

# ── Build / publish ────────────────────────────────────────────────────────────

build:
	rm -rf dist
	uv build

publish-test: build
	@if [ -z "$$UV_PUBLISH_TOKEN" ]; then \
		echo "  UV_PUBLISH_TOKEN is not set."; \
		echo "  Get a token at https://test.pypi.org/manage/account/token/"; \
		echo "  Then: export UV_PUBLISH_TOKEN=pypi-..."; \
		exit 1; \
	fi
	uv publish --publish-url https://test.pypi.org/legacy/

publish: build
	@if [ -z "$$UV_PUBLISH_TOKEN" ]; then \
		echo "  UV_PUBLISH_TOKEN is not set."; \
		echo "  Get a project-scoped token at https://pypi.org/manage/account/token/"; \
		echo "  Then: export UV_PUBLISH_TOKEN=pypi-..."; \
		exit 1; \
	fi
	@echo "WARNING  About to publish to PyPI (real, public, irrevocable for this version)."
	@read -p "         Type 'yes' to continue: " confirm && [ "$$confirm" = "yes" ]
	uv publish
