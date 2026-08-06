-- A-E-03 pg16 schema for the cost ledger.
-- Unique (decision_id, step_idx); ingest is idempotent via ON CONFLICT.
-- Token buckets are stored exclusive (input_tokens excludes cached_input_tokens).

CREATE TABLE IF NOT EXISTS steps (
  decision_id          TEXT NOT NULL,
  step_idx             INTEGER NOT NULL CHECK (step_idx >= 0),
  model                TEXT NOT NULL,
  provider             TEXT NOT NULL,
  quantization         TEXT,
  input_tokens         INTEGER NOT NULL CHECK (input_tokens >= 0),
  cached_input_tokens  INTEGER NOT NULL CHECK (cached_input_tokens >= 0),
  output_tokens        INTEGER NOT NULL CHECK (output_tokens >= 0),
  cache_event          TEXT NOT NULL CHECK (cache_event IN ('miss','hit','write','provider_inclusive')),
  latency_ms           DOUBLE PRECISION NOT NULL CHECK (latency_ms >= 0),
  prompt_fingerprint   TEXT,
  quality_signal       DOUBLE PRECISION,
  ts                   TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (decision_id, step_idx)
);

CREATE TABLE IF NOT EXISTS budget_events (
  decision_id     TEXT NOT NULL,
  step_idx        INTEGER NOT NULL CHECK (step_idx >= 0),
  estimated_tokens DOUBLE PRECISION NOT NULL CHECK (estimated_tokens >= 0),
  budget          DOUBLE PRECISION NOT NULL CHECK (budget >= 0),
  outcome         TEXT NOT NULL CHECK (outcome IN ('pass','blow')),
  PRIMARY KEY (decision_id, step_idx)
);

CREATE TABLE IF NOT EXISTS cache_events (
  decision_id          TEXT NOT NULL,
  step_idx             INTEGER NOT NULL CHECK (step_idx >= 0),
  region_hashes        JSONB NOT NULL,
  cache_event          TEXT NOT NULL CHECK (cache_event IN ('miss','hit','write','provider_inclusive')),
  input_tokens         INTEGER NOT NULL CHECK (input_tokens >= 0),
  cached_input_tokens  INTEGER NOT NULL CHECK (cached_input_tokens >= 0),
  ts                   TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (decision_id, step_idx)
);

CREATE TABLE IF NOT EXISTS price_snapshots (
  id           SERIAL PRIMARY KEY,
  provider     TEXT NOT NULL,
  model        TEXT NOT NULL,
  input_per_mtok      DOUBLE PRECISION NOT NULL,
  cached_input_per_mtok DOUBLE PRECISION NOT NULL,
  output_per_mtok     DOUBLE PRECISION NOT NULL,
  cache_write_per_mtok DOUBLE PRECISION NOT NULL,
  captured_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_steps_decision ON steps (decision_id);
CREATE INDEX IF NOT EXISTS idx_steps_fingerprint ON steps (prompt_fingerprint);
CREATE INDEX IF NOT EXISTS idx_cache_events_region ON cache_events USING gin (region_hashes);
