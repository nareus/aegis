-- Migration 003: Interview sessions for prep agent
-- Tracks mock system-design and behavioral sessions, per-company readiness

CREATE TABLE interview_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          UUID REFERENCES job_applications(id) ON DELETE SET NULL,
    company         TEXT,                               -- denormalised for jobless sessions
    session_type    TEXT NOT NULL,                      -- system-design | behavioral
    question        TEXT NOT NULL,
    answer          TEXT,
    feedback        TEXT,
    score           REAL,                               -- 0.0-1.0 evaluated by LLM
    weak_areas      TEXT[],                             -- patterns/skills to improve
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    answered_at     TIMESTAMPTZ
);

CREATE INDEX idx_interview_job_id     ON interview_sessions(job_id);
CREATE INDEX idx_interview_company    ON interview_sessions(company);
CREATE INDEX idx_interview_type       ON interview_sessions(session_type);
CREATE INDEX idx_interview_score      ON interview_sessions(score DESC NULLS LAST);

INSERT INTO schema_migrations (version) VALUES ('003');
