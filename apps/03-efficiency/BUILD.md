# Build · @substrate/efficiency (03) — Token Economics and Performance Engineering

> **Read this file + `docs/PLAN.md` (contracts) + `packages/substrate` (implementation). You do NOT need to read other units' files.** Spec: `apps/03-efficiency/SPEC.md`.
>
> **Constraint: LOCAL-ONLY Docker Compose. LLM via Ollama default (:11434) / LiteLLM (:4000). Peak via env key, never a runtime dependency.**
>
> **Language: TS-first (pnpm) with Python services only where the ecosystem demands it (LiteLLM, FastAPI, Langfuse).**

## Interface contract

**Imports:** 01's decision log join key (`decisionId`), run events, and the render surface that consumes wire discipline · 02's confidence (`POST :8020/confidence`) as the tiering signal · `@substrate/substrate` (C4 ledger, C7 wire, eval core).
**Exports:** `POST :8100/steps` ledger ingest (C4) · `POST :8102/v1/chat/completions` routed OpenAI-compatible gateway · wire discipline library (registry + deltas + instruction blocks) consumed by 01's render surface.

**Non-negotiables:** token buckets are EXCLUSIVE (`inputTokens` excludes `cachedInputTokens`); cost ledger rows always carry `decisionId`; quantization honesty measured AT THE GATE (gate-pass/outcome rates), never perplexity; TCO is honest about non-token costs (latency, ops, hardware).

## Port map (allocated)

||| 8100 ledger-api · 8101 cache-analytics · 8102 routing · 8103 budget-gate · 8104 escalation-monitor · 4000 litellm |||

## Molecules & atoms

### M1 — Cost Ledger

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-E-01 | `ledger-schema` (StepRecord/BudgetEvent, OTel GenAI-aligned attrs) | lib | TS+zod | v1 |
| A-E-02 | `ledger-api` (POST /steps, GET by decision_id) | svc :8100 | FastAPI | v1 |
| A-E-03 | `ledger-db` (steps, cache_events, budgets, price_snapshots; unique (decision_id, step_idx)) | db | pg16 | v1 |
| A-E-04 | `token-accounting` (exclusive-bucket normalization: tiktoken + HF tokenizers + @anthropic-ai/tokenizer) | lib | TS | v1 |
| A-E-05 | `provider-adapter` (LiteLLM SDK → normalized StepRecord; Ollama first-class) | lib | TS | v1 |
| A-E-06 | `budget-gate` (blow = a decision → 01 gate, never a crash) | svc :8103 | FastAPI | v1 |
| A-E-07 | `otel-genai-export` | lib | OTel | v2 |
| A-E-08 | `ledger-replay-cli` (replays 01 recorded runs through the ledger) | cli | TS | v1 |

### M2 — Cache Analytics

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-E-09 | `cache-event-ingest` (Anthropic exclusive + OpenAI inclusive → CacheEvent) | lib | TS | v1 |
| A-E-10 | `prompt-fingerprinter` (region hashes: identity/task/tools/schemas/few-shot/dynamic) | lib | canonical JSON+SHA-256 | v1 |
| A-E-11 | `cache-analytics` (hit-rate by region, reuse-by-design vs stagnation classifier) | svc :8101 | FastAPI | v1 |
| A-E-12 | `cache-simulator` (would-be hit rate under a stable-block plan) | lib | TS | v1 |
| A-E-13 | `local-kv-cache` (vLLM APC / LMCache) | svc | GPU optional | v2 |

### M3 — Routing Controller

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-E-14 | `routing-policy` ((model, provider, quantization) tuple policy, confidence-gated tiering) | lib | TS declarative | v1 |
| A-E-15 | `routing-service` (LiteLLM gateway + policy enforcement, emits StepRecord) | svc :8102 + :4000 | FastAPI+LiteLLM | v1 |
| A-E-16 | `confidence-adapter` (02 C5 → tier thresholds) | lib | TS | v1 |
| A-E-17 | `routing-calibrator` (RouteLLM-style offline threshold calibration per workload) | cli | TS | v1 |
| A-E-18 | `escalation-monitor` (tiering-cascade meter: escalation/reject rate per tier) | svc :8104 | FastAPI | v1 |

### M4 — Wire Discipline Library

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-E-19 | `schema-registry` (versioned wire schemas: tool-schemas, render_ui, memory) | lib+data | JSON Schema+zod | v1 |
| A-E-20 | `delta-protocol` (RFC 6902 diff/apply + squash-to-full heuristic) | lib | fast-json-patch+jsondiffpatch | v1 |
| A-E-21 | `wire-golden-tests` (byte-exact golden patches; regression net) | test | vitest | v1 |
| A-E-22 | `render-ui-toy` (OpenUI-style compact streaming DSL + delta edits) | lib | TS | v1 |
| A-E-23 | `instruction-blocks` (6-layer cache-stable prompt assembly) | lib | TS | v1 |

### M5 — Marginal-Token-Utility Harness

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-E-24 | `mtu-harness` (ablates prompt regions per task family; quality axis = 02 gate verdicts) | bench | vitest+Ollama | v1 |
| A-E-25 | `task-families` (classification, extraction, code-gen, UI-gen, retrieval-answer; easy/hard splits) | dataset | JSONL | v1 |
| A-E-26 | `mtu-report` (token-bucket contribution ranking per family) | cli | TS | v1 |

### M6 — TCO Model

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-E-27 | `tco-model` (workload → cost curves; lever grid = tier × quant × cache × provider; non-token honest) | lib | TS | v1 |
| A-E-28 | `price-catalog` (seeded from LiteLLM prices; cache write/read rates; local quant costs) | data | JSON snapshots | v1 |
| A-E-29 | `tco-cli` (predict + validate against actual bill) | cli | TS | v1 |

### M7 — Benchmarks

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-E-30 | `e2e-cost-bench` (baseline vs routed vs cached vs delta; ≥50% cost drop @ equal outcomes) | bench | TS+01 workload | v1 |
| A-E-31 | `quant-honesty-bench` (gate-pass/outcome rates per GGUF quant; vLLM FP8 v2) | bench | Ollama | v1/v2 |
| A-E-32 | `delta-100th-turn-bench` (90% claim at turn 100; squash crossover) | bench | TS | v1 |

### M8 — Ops & Observability

| WP | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-E-33 | `compose-stack` (ledger, cache-analytics, routing+litellm, pg, ollama, prometheus, grafana, langfuse-optional) | infra | compose | v1 |
| A-E-34 | `dashboards` (cost/step by tier, cache hit by region, tier mix, latency p50-p99, budget burn) | config | Grafana+Prometheus | v1 |
| A-E-35 | `unit-README` (atoms ↔ success signals mapping + runbook) | docs | markdown | v1 |

## Acceptance (= SPEC success signals)

1. MTU study: token buckets rank by contribution, task-family split, honest "which part of your prompt pays for itself".
2. Cost per completed task drops **≥50% at equal outcome rates** on a reference workload, attributable in the ledger (e2e-cost-bench).
3. TCO predicts the observed bill within a stated margin across two workloads (tco-cli validate).
4. Cache-first/routing/delta stack holds at reference latency budgets.

## Runbook (after build)

```
make up            # compose (ledger, routing+litellm, pg, prometheus, grafana)
make replay-ledger # replay 01 runs through ledger (needs 01 goldens)
make mtu           # marginal-token-utility harness → docs/validation/
make e2e-cost      # headline benchmark
make tco validate  # TCO vs actual bill
```