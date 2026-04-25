-- Aegis v0.2: Tracing and eval harness tables

-- Every agent call across the system. A workflow run produces a tree of spans
-- (root span has parent_span_id IS NULL).
CREATE TABLE IF NOT EXISTS agent_traces (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID NOT NULL,
    parent_span_id  UUID REFERENCES agent_traces(id),
    agent_name      TEXT NOT NULL,
    workflow        TEXT NOT NULL,
    input_payload   JSONB NOT NULL,
    output_payload  JSONB,
    error           TEXT,
    cost_usd        NUMERIC(10, 6),
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    latency_ms      INTEGER,
    started_at      TIMESTAMPTZ NOT NULL,
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_traces_run_id ON agent_traces(run_id);
CREATE INDEX IF NOT EXISTS idx_traces_workflow ON agent_traces(workflow);
CREATE INDEX IF NOT EXISTS idx_traces_started_at ON agent_traces(started_at);

-- Aggregate per-suite eval results
CREATE TABLE IF NOT EXISTS eval_runs (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    eval_name         TEXT NOT NULL,
    git_sha           TEXT,
    triggered_by      TEXT NOT NULL,
    score             REAL NOT NULL,
    case_count        INTEGER NOT NULL,
    pass_count        INTEGER NOT NULL,
    detailed_results  JSONB,
    total_cost_usd    NUMERIC(10, 6),
    started_at        TIMESTAMPTZ NOT NULL,
    completed_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_eval_runs_name_started ON eval_runs(eval_name, started_at DESC);

-- Mirror of YAML golden cases for analysis queries
CREATE TABLE IF NOT EXISTS eval_golden_cases (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    eval_name       TEXT NOT NULL,
    case_id         TEXT NOT NULL,
    input_payload   JSONB NOT NULL,
    expected_output JSONB NOT NULL,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (eval_name, case_id)
);

-- Link saved jobs to their multi-agent analysis traces and refinement metadata
ALTER TABLE job_applications
    ADD COLUMN IF NOT EXISTS critic_feedback   JSONB,
    ADD COLUMN IF NOT EXISTS refinement_count  INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS analysis_run_id   UUID;

INSERT INTO schema_migrations (version) VALUES (4) ON CONFLICT DO NOTHING;
