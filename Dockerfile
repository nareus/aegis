# syntax=docker/dockerfile:1
# Multi-stage build: builder installs deps, runtime is lean

# ── Stage 1: builder ────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first (layer cache)
COPY pyproject.toml uv.lock ./

# Install dependencies into /build/.venv (no project code yet)
RUN uv sync --frozen --no-install-project --no-dev

# Copy source and install the project itself
COPY src/ src/
RUN uv sync --frozen --no-dev


# ── Stage 2: runtime ────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

# psql for running migrations in entrypoint
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN addgroup --system aegis && adduser --system --ingroup aegis aegis

# Copy virtualenv from builder
COPY --from=builder /build/.venv /app/.venv

# Copy source (needed for package imports)
COPY --from=builder /build/src /app/src

# Copy migrations (applied at startup via entrypoint)
COPY migrations/ /app/migrations/

# Copy entrypoint
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# Activate venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER aegis

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["api"]
