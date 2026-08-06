# Build · @substrate/knowledge (04) — Operating Retrieval Like It's a Database

> **Read this file + `docs/PLAN.md` (contracts) + `packages/substrate` (implementation). You do NOT need to read other units' files.** Spec: `apps/knowledge/SPEC.md`.
>
> **Constraint: LOCAL-ONLY Docker Compose. LLM via Ollama default (:11434) / vLLM optional. Peak via env key, never a runtime dependency.**
>
> **Language: Python (`py/` uv workspace) — Docling, Instructor, Splink, LightRAG-reference, Evidently demand it.**

## Interface contract

**Imports:** 01's decision log outcomes (retrieval-quality labels, via C2/DB) · `@substrate/substrate` (C3 verdicts, C6 scenarios, eval core).
**Exports:** C3 retrieval verdicts via `POST :8204/gate` (support/contradict/silent, calibrated) · corpus properties + extraction quality as dimensions for 05's worlds · verdict stream into 01's event log.

**Stack decisions (locked):** Qdrant single-node (vector) · **FalkorDB** (graph; Kuzu archived, excluded) · Postgres (metadata/ledgers) · **LightRAG as reference baseline only, NOT a dependency** (we build our own assembler/retrieval so extraction evals + gates are first-class) · borrow Graphiti temporal-fact semantics (validity windows, invalidation) · Docling for parsing · **Instructor** for typed extraction, **Outlines** constrained decoding for verdicts · **Splink/DuckDB** for resolution · Evidently + t-digest for drift, APScheduler for re-ingestion (no Kafka; CDC only under k3s v2).

## Port map (allocated)

||| 8201 characterize · 8202 human-queue · 8203 subgraph · 8204 grounded-gate |||

## Molecules & atoms

### M1 — Task Characterization

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-K-01 | `corpus-structural-profiler` (multi_hop_index, contradiction_index, stance_distribution, aggregation_share) | lib | python+numpy/spaCy | v1 |
| A-K-02 | `characterization-decision-api` (vector / vector+graph / graph-only + opinionated refusal) | svc :8201 | FastAPI | v1 |
| A-K-03 | `characterization-suite` (corpus suite with known-best architectures) | bench | pytest | v1 |
| A-K-04 | `property-probes` (multi-hop reachability, contradiction-pair, stance labeling) | lib | python | v1 |

### M2 — Extraction

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-K-05 | `ingestion-pipeline` (Docling parse → canonical chunks) | svc | Docling client | v1 |
| A-K-06 | `type-constrained-extractor` (ontology-typed entities/relations, schema-violation reporting) | svc | Instructor+Pydantic | v1 |
| A-K-07 | `extraction-eval-harness` (precision/recall/type-violation on slices; continuous score) | lib+cli | python | v1 |
| A-K-08 | `round-trip-validator` (extract → re-embed → verify relation recoverability) | svc | python | v1 |
| A-K-09 | `extraction-telemetry-store` (scores, violations, per-doc rollups) | db | pg | v1 |
| A-K-10 | `golden-slices-dataset` (real docs + LLM-assisted labels + human spot-check) | dataset | git/DVC | v1 |

### M3 — Entity Resolution

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-K-11 | `blocker` (blocking keys: canonical name, type, source, date) | lib | Splink | v1 |
| A-K-12 | `similarity-scorer` (Fellegi-Sunter + embedding cosine fusion) | lib | Splink/DuckDB | v1 |
| A-K-13 | `resolution-calibrator` (precision-at-ambiguity-band, R4) | lib | python | v1 |
| A-K-14 | `human-confirmation-queue` (merge/split/skip UI + audit) | svc :8202 | FastAPI+UI | v1 |
| A-K-15 | `canonicalization-store` (canonical ids, alias map, merge audit, source refs) | db | pg | v1 |

### M4 — Graph Assembly + Store

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-K-16 | `graph-assembler` (upsert resolved facts + provenance + validity windows) | svc | FalkorDB client | v1 |
| A-K-17 | `graph-store` | db | FalkorDB (lite fallback) | v1 |
| A-K-18 | `vector-store` (chunk/entity/relation collections + payload filters) | db | Qdrant (LanceDB alt) | v1 |
| A-K-19 | `subgraph-extractor` (query → candidate entities → bounded evidence subgraph) | svc :8203 | Cypher+vector | v1 |
| A-K-20 | `ontology-registry` (the single type-constrained schema; entity/edge types + constraints) | lib+db | Pydantic | v1 |

### M5 — Freshness

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-K-21 | `source-change-detector` (content-hash polling; CDC v2) | svc | python watchers | v1 |
| A-K-22 | `drift-monitor` (source-vs-graph: PSI, embedding/text drift, t-digest percentiles) | lib | Evidently+t-digest | v1 |
| A-K-23 | `re-ingestion-scheduler` (targeted doc-level jobs, cost hooks) | svc | APScheduler+Redis | v1 |
| A-K-24 | `freshness-ledger` (per-source last-ingested, staleness age, trigger history, cost) | db | pg | v1 |

### M6 — Grounded Gate

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-K-25 | `verdict-classifier` (Outlines constrained: Literal[support, contradict, silent] + confidence + cited evidence) | lib | python | v1 |
| A-K-26 | `grounded-gate-service` (`POST /gate {claim, subgraph}` → verdict or blocked; veto log) | svc :8204 | FastAPI | v1 |
| A-K-27 | `verdict-store` (verdict history, support rate per source/query; feeds 02) | db | pg | v1 |

### M7 — Observability

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-K-28 | `graph-health-monitor` (entity coverage per source, relation density, orphan-cluster drift, connectivity) | lib | python | v1 |
| A-K-29 | `metrics-exporter` (Prometheus /metrics) | lib | prom-client | v1 |
| A-K-30 | `observability-dashboard` (support rate, extraction trend, staleness age, queue depth) | ui | Grafana | v2 (min v1) |

### M8 — Benchmarks

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-K-31 | `graph-vs-flat-runner` (equal-cost graph vs flat-index; R1) | bench | pytest | v1 |
| A-K-32 | `extraction-error-propagation` (inject error rates → correct-evidence resolution; R2) | bench | pytest | v1 |
| A-K-33 | `freshness-economics` (stale cost vs re-ingest cost; R3) | bench | pytest | v2 |
| A-K-34 | `gate-effectiveness` (gated vs ungated retrieval-borne errors, 01 outcomes; R5) | bench | pytest | v2 |
| A-K-35 | `retrieval-qa-suite` (RAGAS metrics + MultiHop-RAG-style tasks) | dataset+runner | python | v1 |

### M9 — Platform

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-K-36 | `compose-stack` (qdrant, falkordb, pg, docling-serve, redis, workers, APIs; profiles) | infra | compose | v1 |
| A-K-37 | `llm-provider-abstraction` (OpenAI-compat wrapper + embeddings + structured-output negotiation) | lib | python | v1 |
| A-K-38 | `message-bus` (Redis streams + pg outbox fallback; topics: source.changed, document.parsed, extraction.complete, gate.verdict) | infra | Redis | v1 |
| A-K-39 | `knowctl` CLI (characterize, ingest, eval-extraction, resolve, gate, monitor, bench) | cli | typer | v1 |

## Acceptance (= SPEC success signals)

1. Published decision rule "vector vs vector+graph vs graph-only" with data behind it (characterization-suite + graph-vs-flat-runner).
2. Extraction error is visible AND decreasing (telemetry + evals); freshness held by gates; evidence grounded-checked — an operator, not a dashboard.
3. At least one workload where the grounded gate caught a retrieval failure a flat index shipped.
4. Extraction-error propagation curve (R2) measured, not hand-waved.

## Runbook (after build)

```
make up && make migrate
knowctl characterize --corpus <dir>      # :8201 verdict
knowctl ingest <docs>                     # Docling → chunks → extract → resolve → assemble
knowctl eval-extraction                   # labeled slices + round-trip
knowctl gate --claim "X" --subgraph ...   # :8204 support/contradict/silent
knowctl bench                             # R1/R2 suites → docs/validation/
```