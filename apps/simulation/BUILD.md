# Build · @substrate/simulation (05) — Calibrated Behavioral Simulation

> **Read this file + `docs/PLAN.md` (contracts) + `packages/substrate` + `packages/scenarios` (implementation). You do NOT need to read other units' files.** Spec: `apps/simulation/SPEC.md`.
>
> **Constraint: LOCAL-ONLY Docker Compose. LLM via Ollama default (:11434) / LiteLLM (:4000). Peak via env key, never a runtime dependency.**
>
> **Language: Python (`py/` uv workspace) + a small TS bridge package for substrate interop.**

## Interface contract

**Imports:** `@substrate/scenarios` (C6 shock seeds, already filled) · `@substrate/substrate` (C6 schema, eval core) · 04's corpus properties (A-K-01) as world-dimension inputs · 02's calibration discipline.
**Exports:** `POST :8300/scenarios` (shock scenarios for 01 stress-testing) · synthetic worlds (`WorldTemplate`) for 02's gated-data ingest · social log in C1 event-log format.

**INTEGRITY RULES (non-negotiable):**
1. **No lookahead bias** — retro-validation uses FRED **ALFRED vintages** (point-in-time); SimBench refuses non-vintaged runs.
2. **2025 tariff wave = end-to-end HOLDOUT** — never used for calibration or seed tuning. Ever.
3. **No global scheduler** in presence-core — moves are urgency-driven, not queue-position-driven (AI-Metropolis out-of-order execution is the published precedent).
4. Cost measured per agent per round (`cost-meter`) — the tiny+frontier hybrid + pruning + slice-and-scale are the cost-ceiling levers.

## Port map (allocated)

||| 8300 sim-api · 8301 probes-human · 8302 seed-synth · 8303 simbench-runner |||

## Molecules & atoms

### M1 — SimBench Core

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-S-01 | `simbench-core` (score_ensemble: coverage 50/80/95, Brier, CRPS, tail_loss) | lib | scoringrules+scipy | v1 |
| A-S-02 | `simbench-runner` (4 shocks × seeds × simulators matrix → Parquet) | cli+svc :8303 | FastAPI+ray | v1 |
| A-S-03 | `simbench-registry` (SimulatorAdapter plugin registry) | lib | python+SQLite | v1 |
| A-S-04 | `simbench-report` (reliability diagrams, coverage tables, win/lose partition) | report | Quarto+Plotly | v1 |
| A-S-05 | `simbench-suite` (golden numbers, fixed seeds) | test | pytest | v1 |

### M2 — Historical Shock Datasets

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-S-06 | `shock-2020-pandemic` (retail/labor/travel + realized path + vintages) | dataset | Parquet+DuckDB | v1 |
| A-S-07 | `shock-2021-supplychain` (PPI, supplier deliveries, freight) | dataset | Parquet | v1 |
| A-S-08 | `shock-2022-inflation` (CPI/PCE core, wages, expectations) | dataset | Parquet | v1 |
| A-S-09 | `shock-2025-tariff` (**HOLDOUT**) | dataset | Parquet | v1 |
| A-S-10 | `fred-ingest` (ALFRED vintages, point-in-time) | svc | fredapi | v1 |
| A-S-11 | `macro-catalog` (series registry: units, freq, source, revision policy) | registry | JSON/YAML | v1 |

### M3 — Statistical Baseline

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-S-12 | `baseline-arima` (AutoARIMA/ETS) | lib/svc | statsforecast | v1 |
| A-S-13 | `baseline-lightgbm` (quantile + conformal intervals) | lib/svc | mlforecast+MAPIE | v1 |
| A-S-14 | `baseline-hub` (ForecastAdapter; lookahead-free backtest w/ vintages) | lib | python | v1 |

### M4 — Simulation Engine (hybrid reference impl)

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-S-15 | `swarm-core` (agents + world → trajectory ensemble) | lib | asyncio+Mesa | v1 |
| A-S-16 | `sim-world` (SKUs/sectors/macro variables; clock + event bus) | lib | python | v1 |
| A-S-17 | `agent-proto` (decision rules + pluggable LLM augment) | lib | python | v1 |
| A-S-18 | `ensemble-store` (seeded reproduces + RNG stream registry) | lib | Parquet+DuckDB | v1 |
| A-S-19 | `simulator-adapter-sdk` (score ANY simulator via plugin contract) | sdk | python | v1 |

### M5 — Seed-Material Synthesizer

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-S-20 | `seed-synth` (macro snapshot → narrative world doc) | svc :8302 | LiteLLM→Ollama | v1 |
| A-S-21 | `seed-schema` (world-doc schema, versioning, coherence lint) | lib | JSON Schema | v1 |
| A-S-22 | `seed-eval` (R3: seed-prose → output-distribution shift) | probe | python | v2 |

### M6 — Injection Library

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-S-23 | `injection-spec` (Shock{profile, magnitude, channels, start}) | schema | JSON Schema | v1 |
| A-S-24 | `shock-scenarios` (4 scenarios + growing family) | configs | reads G-02 | v1 |
| A-S-25 | `injection-runtime` (replayable interventions for sims AND baselines; reuse by 01 stress) | lib | python | v1 |

### M7 — Presence Engine

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-S-26 | `presence-core` (urgency heap, no global scheduler; attention/interpretation/motivation/emotion/pressure/inhibition/memory) | lib | asyncio | v1 |
| A-S-27 | `affect-models` (Russell circumplex 2D + PAD + ACT-lite update rules) | lib | numpy | v1 |
| A-S-28 | `memory-store` (episodic memory, social graph, alliance state) | svc | DuckDB+embeddings | v1 |
| A-S-29 | `presence-llm` (tiny+frontier policy, pruning hooks) | lib | LiteLLM | v1 |
| A-S-30 | `social-log` (post, reply, lurk, silence, alliance → C1 event format) | stream | JSONL | v1 |

### M8 — Believability Probes

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-S-31 | `probes-behavioral` (interruption, lurking, latency dist, silence-misreading, alliance) | lib | python | v1 |
| A-S-32 | `probes-human` (annotation UI + "room of people" rubric + inter-annotator stats) | app :8301 | FastAPI | v2 |
| A-S-33 | `calibration-corpus` (ConvoKit: Switchboard/Diplomacy/GAP) | data | convokit | v1 |
| A-S-34 | `probe-report` (presence vs turn-based control) | report | Quarto+Plotly | v1 |

### M9 — Cross-cutting

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-S-35 | `cost-meter` (per-agent/per-round ledger; pruning + slice-and-scale hooks) | lib | python | v1 |
| A-S-36 | `sim-db` (canonical: runs, trajectories, scores, corpus cache) | db | DuckDB | v1 |
| A-S-37 | `sim-api` (REST :8300; A2A endpoint v2) | svc | FastAPI | v1/v2 |
| A-S-38 | `compose` + Makefile | infra | compose | v1 |
| A-S-39 | `substrate-bridge` (TS pkg: publishes scenarios + social log to substrate) | lib | TS | v1 |
| A-S-40 | `research-reports` (R1-R6 Quarto notebooks) | docs | Quarto | v2 |

## Acceptance (= SPEC success signals)

1. SimBench exists; a coverage/calibration claim reproduces across simulators (adapter SDK + registry). Coverage 50/80/95 on 3 shocks; 2025 = untouched holdout.
2. Hybrid shows a measured edge on the cascade category and an honest null result on steady-state.
3. Presence-engine room: an observer watches lurking, silence-misreading, and an alliance WITHOUT the script writing them.
4. Probes published vs turn-based baseline; `presence` library plugs into another simulation and improves social realism measurably.
5. Injection library reused by 01's stress-testing — the ecosystem link proven by use.

## Runbook (after build)

```
make up
simbench run --matrix        # 4 shocks × seeds × simulators → sim-db
make retro                   # A-S-01 scoring on 2020/2021/2022 (2025 holdout untouched)
make baseline                # statsforecast + lightgbm quantile arms
make presence                # run a room, record social log
make probes                  # behavioral + report vs turn-based control
```