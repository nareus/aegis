-- Aegis v0.1 initial schema

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Schema migration tracking
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Every briefing run, successful or failed
CREATE TABLE IF NOT EXISTS briefing_runs (
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

CREATE INDEX IF NOT EXISTS idx_briefing_runs_triggered_at ON briefing_runs (triggered_at DESC);
CREATE INDEX IF NOT EXISTS idx_briefing_runs_status ON briefing_runs (status);

-- Pointer to current latest successful run (single row)
CREATE TABLE IF NOT EXISTS briefing_latest (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    run_id      UUID NOT NULL REFERENCES briefing_runs(run_id),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Track migration version
INSERT INTO schema_migrations (version) VALUES (1) ON CONFLICT DO NOTHING;
