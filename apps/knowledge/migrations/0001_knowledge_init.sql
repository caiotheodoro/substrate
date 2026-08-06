-- @substrate/knowledge (04) — schema bootstrap.
-- Runs automatically on first pg start (docker-entrypoint-initdb.d).

CREATE SCHEMA IF NOT EXISTS knowledge;

-- Generic KV backing store for telemetry / canonicalization / verdict /
-- freshness-ledger atoms (PostgresStore.ensure_schema keeps this idempotent).
CREATE TABLE IF NOT EXISTS substrate_knowledge_kv (
    kind text NOT NULL,
    key text NOT NULL,
    value jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (kind, key)
);

CREATE INDEX IF NOT EXISTS substrate_knowledge_kv_kind_key_idx
    ON substrate_knowledge_kv (kind, key);

-- A-K-38 message-bus Postgres outbox fallback.
CREATE TABLE IF NOT EXISTS bus_outbox (
    id text PRIMARY KEY,
    topic text NOT NULL,
    payload jsonb NOT NULL,
    published_at timestamptz NOT NULL DEFAULT now()
);

-- A-K-09 extraction telemetry rollups (per-doc).
CREATE TABLE IF NOT EXISTS extraction_telemetry (
    doc_id text PRIMARY KEY,
    n_entities integer NOT NULL DEFAULT 0,
    n_relations integer NOT NULL DEFAULT 0,
    n_violations integer NOT NULL DEFAULT 0,
    score double precision NOT NULL DEFAULT 0,
    recorded_at timestamptz NOT NULL DEFAULT now()
);
