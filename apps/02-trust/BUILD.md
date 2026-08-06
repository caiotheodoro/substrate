# Build · @substrate/trust (02) — One Measurement Discipline for Actions and Data

> **Read this file + `docs/PLAN.md` (contracts) + `packages/substrate` (implementation). You do NOT need to read other units' files.** Spec: `apps/02-trust/SPEC.md`.
>
> **Constraint: LOCAL-ONLY Docker Compose. LLM via Ollama default (:11434) + llama.cpp `llama serve` for verdict models. Peak via env key, never a runtime dependency.**
>
> **Language: Python (`py/` uv workspace) — the ecosystem (Inspect, uncertainty-toolbox, netcal, Min-K%Pro, HDBSCAN) demands it.**

## Interface contract

**Imports:** 01's decision log (C2 rows via DB or `:8934`/`:8930` API) · 04's retrieval verdicts (C3 via `:8204`) · 05's synthetic worlds (C6 via `:8300`) · `@substrate/substrate` contracts.
**Exports:** C5 `POST :8020/confidence → {score, band, explain, modelVersion}` (drop-in for 01's gate + 03's tiering) · gated dataset library (`trust_gated_data`) for any fine-tune project.

**VERIFICATION HIERARCHY (non-negotiable):** confidence features come ONLY from (1) tool-call returns, (2) retrieval support/contradict/silent, (3) schema/type satisfaction, (4) outcome prediction. **NEVER logprobs / self-consistency / LLM-as-judge.** The banned baselines are measured in ConfBench as baselines to beat — they never feed a production feature.

## Port map (allocated)

||| 8010 tool-call verifier · 8011 retrieval-verdict · 8012 schema-checker · 8020 scorer · 8030 ingest · 8031 verifiability · 8032 label-quality · 8033 contamination · 8034 diversity · 8040 reconciler · 8041 scheduler · 8050/8060 dashboards |||

## Molecules & atoms

### M0 — Platform

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-T-01 | `trust-compose` | infra | compose + .env | v1 |
| A-T-02 | `trust-db` (schemas: decision_log, features, outcomes, model_registry, provenance, quarantine, confbench) | db | pg16 | v1 |
| A-T-03 | `trust-object-store` (buckets: artifacts, datasets, models, quarantine) | db | MinIO | v1 |
| A-T-04 | `trust-bus` | svc | NATS | v2 |
| A-T-05 | `llm-gateway` (Ollama :11434 + llama.cpp `llama serve` :8080) | svc | compose | v1 |
| A-T-06 | `feature-registry` (feature_defs, feature_versions tables) | lib+table | python | v1 |

### M1 — ConfBench

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-T-07 | `confbench-tasks` (ground truth + verifiable artifacts: tool/retrieval/schema/outcome tasks) | dataset | HF datasets | v1 |
| A-T-08 | `confbench-runner` (Inspect AI custom scorers/metrics; promptfoo secondary) | bench | python | v1 |
| A-T-09 | `confbench-metrics` (score-level Brier/ECE/reliability, ndcg_escalation, shift_delta) | lib | uncertainty-toolbox+netcal | v1 |
| A-T-10 | `confbench-holdout` (membership sets + trap documents — NEVER leaked) | dataset | HF | v1 |
| A-T-11 | `shift-generator` (topic/domain/perturbation transforms) | lib | python | v1-lite |
| A-T-12 | `baselines` (logprob, self-consistency, verbalized — banned-but-measured) | bench | sklearn/torch | v1 |
| A-T-13 | `confbench-dashboard` (reliability diagrams, escalation Pareto, shift curves) | app | FastAPI+plotly :8050 | v2 |

### M2 — Signal Extractors

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-T-14 | `tool-call-verifier` (`{ran, result_sign, error, result_schema_ok}` — zero-LLM) | svc :8010 | python/jsonschema | v1 |
| A-T-15 | `retrieval-verdict` (HHEM-2.1 CPU → Glider-3.8B → Lynx-8B ladder, calibrated) | svc :8011 | Ollama/llama.cpp | v1 |
| A-T-16 | `schema-checker` (`{satisfied, violation_kind}`) | svc :8012 | JSON Schema+GBNF | v1 |
| A-T-17 | `evidence-features` (extractors + outcome history → feature rows) | lib | python | v1 |

**Ladder note (A-T-15):** cheap-first is a design constraint: HHEM-2.1 always-on, escalate to Glider/Lynx on low confidence. Verdict probabilities are recalibrated by the same netcal pipeline as the scorer.

### M3 — Trust Scorer

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-T-18 | `scorer-train` (LightGBM + netcal isotonic/Platt, CV; MLflow log v2) | cli | python | v1 |
| A-T-19 | `scorer-serve` `POST /confidence` + per-feature explain | svc :8020 | FastAPI+ONNX | v1 |
| A-T-20 | `model-registry` (models, model_versions, model_cards) | table+lib | pg+MinIO | v1-lite |
| A-T-21 | `mlp-baseline` (R3 ablation) | exp | torch | v2 |

### M4 — Gated Data Pipeline

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-T-22 | `data-ingest` (seeds from 05 worlds / real docs / decision log; provenance stamping) | svc :8030 | python | v1 |
| A-T-23 | `verifiability-gate` (per-sample checkable+true) | svc :8031 | uses A-T-14/15/16 | v1 |
| A-T-24 | `label-quality-gate` (sampling + HITL review queue) | svc :8032 | python | v1-lite |
| A-T-25 | `contamination-gate` (Min-K%Pro vs local ref model + MinHash LSH + n-gram vs holdout + Faiss near-dup; quarantine) | svc :8033 | python | v1 |
| A-T-26 | `diversity-steering` (Ollama embeddings + HDBSCAN + Faiss coverage) | svc :8034 | python | v1 |
| A-T-27 | `provenance-tracker` (per-sample lineage source→gates→dataset version) | lib+table | python | v1 |
| A-T-28 | `gated-dataset-lib` `gate(seed, policy) → Dataset` (the reusable deliverable) | lib | python pkg | v1 |
| A-T-29 | `gated-eval-echo` (fine-tune → gated eval vs ungated) | pipeline | one-shot | v2 |

### M5 — Recalibration Loop

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-T-30 | `decision-log-consumer` (polls 01's decision log → local features/outcomes) | svc | python | v1 |
| A-T-31 | `outcome-reconciler` (pending/confirmed/delayed/conflicting + staleness TTL) | svc :8040 | python | v1 |
| A-T-32 | `recalibration-scheduler` (APScheduler → scorer-train; band-drift report) | svc :8041 | python | v1 |
| A-T-33 | `band-report` (escalation-band tightening dashboard) | app :8060 | FastAPI+plotly | v2 |

### M6 — Research experiments

| WP | Atom | Type | v |
|---|---|---|---|
| A-T-34 | `r1-dominance` (evidence vs self-report under shift, difficulty-controlled) | exp | v1 |
| A-T-35 | `r2-verifiability-audit` (fraction of unverifiable workload → default-escalate) | analysis | v1 |
| A-T-36 | `r3-outcome-features` (feature/model ablations, label-count curves) | exp | v2 |
| A-T-37 | `r4-blindspots` (trap-injected: weak model on strong-model synthetic data) | exp | v2 |
| A-T-38 | `r5-gated-economics` (quarantine/diversity cost-value at equal budget) | exp | v2 |

## Acceptance (= SPEC success signals)

1. ConfBench: evidence-based scoring dominates self-report **under distribution shift** — Brier/ECE at score level + NDCG escalation, curves as PNG artifacts.
2. Scorer-serve injectable into 01 (`POST :8020/confidence` drop-in); escalation band measurably tightens over a real decision log (band-report).
3. Gated-dataset-lib: a fine-tune on gated data beats the ungated baseline at equal budget (r5), with the quarantined slice's negative effect shown.

## Runbook (after build)

```
make up && make migrate
make confbench          # run ConfBench + baselines + shift → docs/validation/
make train-scorer && make serve-scorer   # :8020
make calibrate          # A-T-31/32 loop on imported decision log
make gate-data          # A-T-22..28 over G-02 worlds
```