-- Aegis v0.1: Job tracker and LeetCode progress tables

-- Job applications with fit scoring
CREATE TABLE IF NOT EXISTS job_applications (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company         TEXT NOT NULL,
    role            TEXT NOT NULL,
    url             TEXT,
    source_text     TEXT,
    status          TEXT NOT NULL DEFAULT 'saved',
    fit_score       REAL,
    fit_analysis    JSONB,
    tech_stack      TEXT[],
    salary_range    TEXT,
    location        TEXT,
    remote          BOOLEAN,
    notes           TEXT,
    applied_date    TIMESTAMPTZ,
    last_activity   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON job_applications(status);
CREATE INDEX IF NOT EXISTS idx_jobs_last_activity ON job_applications(last_activity);
CREATE INDEX IF NOT EXISTS idx_jobs_fit_score ON job_applications(fit_score DESC);

-- LeetCode problem tracking by pattern
CREATE TABLE IF NOT EXISTS leetcode_problems (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,
    title_slug      TEXT NOT NULL UNIQUE,
    difficulty      TEXT NOT NULL,
    patterns        TEXT[] NOT NULL,
    url             TEXT,
    solved          BOOLEAN NOT NULL DEFAULT false,
    attempts        INTEGER NOT NULL DEFAULT 1,
    time_complexity TEXT,
    notes           TEXT,
    solved_at       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_leetcode_patterns ON leetcode_problems USING GIN(patterns);
CREATE INDEX IF NOT EXISTS idx_leetcode_difficulty ON leetcode_problems(difficulty);
CREATE INDEX IF NOT EXISTS idx_leetcode_solved ON leetcode_problems(solved);

-- Track migration version
INSERT INTO schema_migrations (version) VALUES (2) ON CONFLICT DO NOTHING;
