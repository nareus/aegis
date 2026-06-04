.PHONY: help test test-unit test-int eval seed-evals lint fmt build dev-install publish-test publish check-clean tag release-gh release

# Read version from pyproject.toml so tag/release/dev-install stay in sync.
VERSION = $$(grep '^version' pyproject.toml | head -1 | sed 's/.*"\(.*\)".*/\1/')

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
	@echo "  make dev-install                Build + install as a uv tool (so 'aegis' on PATH = current code)"
	@echo "  make publish-test               Publish to TestPyPI (needs UV_PUBLISH_TOKEN)"
	@echo "  make publish                    Publish to PyPI    (needs UV_PUBLISH_TOKEN, with confirm)"
	@echo "  make tag                        Tag current pyproject.toml version + push"
	@echo "  make release-gh                 Create GitHub release with wheel + sdist attached"
	@echo "  make release                    Full flow: publish -> tag -> release-gh (with safeguards)"
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

# After this, `aegis` on PATH is your current source. Restart Claude Desktop
# (Cmd-Q + reopen) to make Claude pick up the new binary.
dev-install: build
	uv tool install --force ./dist/aegis_agents-$(VERSION)-py3-none-any.whl
	@echo ""
	@echo "  Installed. 'aegis' on PATH now points at the current build."
	@echo "  Cmd-Q Claude Desktop and reopen so it spawns the new binary."
	@echo ""

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
	@echo "WARNING  About to publish v$(VERSION) to PyPI (real, public, irrevocable for this version)."
	@read -p "         Type 'yes' to continue: " confirm && [ "$$confirm" = "yes" ]
	uv publish

# ── Release ────────────────────────────────────────────────────────────────────

# Refuse to release if there are uncommitted changes — what's tagged must match
# what's published.
check-clean:
	@if [ -n "$$(git status --porcelain)" ]; then \
		echo "  Working tree has uncommitted changes. Commit or stash, then retry."; \
		git status --short; \
		exit 1; \
	fi

# Tag the current pyproject.toml version and push the tag.
# Idempotent: warns and exits 0 if the tag already exists locally.
tag:
	@v=$(VERSION); \
	if git rev-parse "v$$v" >/dev/null 2>&1; then \
		echo "  Tag v$$v already exists locally. Skipping."; \
	else \
		echo "  Tagging v$$v..."; \
		git tag "v$$v" -m "v$$v"; \
	fi; \
	echo "  Pushing tag v$$v..."; \
	git push origin "v$$v"

# Create the GitHub release for the current version, attaching the built wheel + sdist.
# Requires `gh` CLI; release notes auto-generated from commits since the previous tag.
release-gh:
	@v=$(VERSION); \
	if [ ! -f "dist/aegis_agents-$$v-py3-none-any.whl" ]; then \
		echo "  Wheel for v$$v not found in dist/. Run 'make build' first."; \
		exit 1; \
	fi; \
	echo "  Creating GitHub release for v$$v..."; \
	gh release create "v$$v" --title "v$$v" --generate-notes \
		dist/aegis_agents-$$v-py3-none-any.whl \
		dist/aegis_agents-$$v.tar.gz

# Full release flow: clean check -> build + publish -> tag + push -> GitHub release.
# Assumes pyproject.toml version is already bumped and the bump is committed.
# Each step is rerunnable; `publish` will refuse a duplicate version, `tag` is
# idempotent.
release: check-clean publish tag release-gh
	@v=$(VERSION); \
	echo ""; \
	echo "  Released v$$v."; \
	echo "  PyPI:   https://pypi.org/project/aegis-agents/$$v/"; \
	echo "  GitHub: https://github.com/nareus/aegis/releases/tag/v$$v"; \
	echo ""
