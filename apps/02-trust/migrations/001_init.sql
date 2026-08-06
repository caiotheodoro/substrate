-- A-T-02 trust-db: trust schema on shared pg (plan port map :5432).
-- Applied by `make migrate` / trust.db.run_migrations. Local-only.

CREATE SCHEMA IF NOT EXISTS trust;

-- C2 decision rows polled from 01's decision log.
CREATE TABLE IF NOT EXISTS trust.decision_log (
    decision_id   text PRIMARY KEY,
    turn_id       text NOT NULL,
    action        text NOT NULL,
    confidence_features jsonb NOT NULL DEFAULT '{}'::jsonb,
    verdict       text NOT NULL CHECK (verdict IN ('execute', 'escalate', 'reject')),
    outcome       boolean,
    confirmed_at  timestamptz,
    arrived_at    timestamptz NOT NULL DEFAULT now(),
    state         text NOT NULL DEFAULT 'pending'
                  CHECK (state IN ('pending', 'confirmed', 'delayed', 'conflicting'))
);

-- One feature row per decision (A-T-06/17 aligned names).
CREATE TABLE IF NOT EXISTS trust.features (
    decision_id text PRIMARY KEY REFERENCES trust.decision_log(decision_id),
    feature_name text NOT NULL,
    feature_value double precision NOT NULL,
    UNIQUE (decision_id, feature_name)
);

-- Confirmed outcomes feeding scorer-train (A-T-18) and band-drift (A-T-32).
CREATE TABLE IF NOT EXISTS trust.outcomes (
    decision_id   text PRIMARY KEY REFERENCES trust.decision_log(decision_id),
    outcome       boolean NOT NULL,
    confirmed_at  timestamptz NOT NULL,
    reconciled_by text NOT NULL DEFAULT 'outcome-reconciler'
);

-- A-T-20 model registry (v1-lite).
CREATE TABLE IF NOT EXISTS trust.model_registry (
    model_id      text PRIMARY KEY,
    model_name    text NOT NULL,
    version       text NOT NULL,
    artifact_path text NOT NULL,
    features      text[] NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (model_name, version)
);

CREATE TABLE IF NOT EXISTS trust.model_cards (
    model_id    text PRIMARY KEY REFERENCES trust.model_registry(model_id),
    card        jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- A-T-27 per-sample lineage.
CREATE TABLE IF NOT EXISTS trust.provenance (
    sample_id       text PRIMARY KEY,
    source          text NOT NULL,
    world           text NOT NULL,
    dataset_version text,
    events          jsonb NOT NULL DEFAULT '[]'::jsonb
);

-- A-T-25 quarantine bucket mirror (rejected samples stay visible).
CREATE TABLE IF NOT EXISTS trust.quarantine (
    sample_id text PRIMARY KEY,
    reason    text NOT NULL,
    payload   jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- A-T-07/08 confbench tasks and runs.
CREATE TABLE IF NOT EXISTS trust.confbench_tasks (
    task_id    text PRIMARY KEY,
    kind       text NOT NULL,
    difficulty double precision NOT NULL,
    evidence   jsonb NOT NULL DEFAULT '{}'::jsonb,
    self_report jsonb NOT NULL DEFAULT '{}'::jsonb,
    outcome    boolean NOT NULL,
    holdout    boolean NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS trust.confbench_runs (
    run_id     text PRIMARY KEY,
    ran_at     timestamptz NOT NULL DEFAULT now(),
    results    jsonb NOT NULL DEFAULT '{}'::jsonb
);
