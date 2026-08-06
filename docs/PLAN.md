# Substrate — Build Plan (Phase 0 lock)

> The single source of truth for anything shared across the 5 units. Each unit's `BUILD.md` is self-contained; subagents never need to read another unit's file — only this doc's contracts section + their own `BUILD.md` + `packages/substrate`.

## 0 · Conventions

- **Deployment**: Docker Compose only, local-only. No cloud services. k3s is an explicit v2 profile, never the default.
- **LLM access**: every LLM touchpoint goes through an OpenAI-compatible client. Default = **Ollama :11434** (native macOS for Metal; container for Linux CI). Frontier models (peak validation) are env-key gated (`SUBSTRATE_PEAK_*`) and NEVER a runtime dependency.
- **Versioning**: `v1` = operable loop (build now). `v2` = fast-follow/economics (listed, not built).
- **Language split**: TS + pnpm for 01/03 + all shared packages; Python (`py/` uv workspace) for 02/04/05 where the ecosystem demands it (Inspect, LightRAG, Splink, Mesa, scoringrules).
- **Atom IDs**: `A-<H|T|E|K|S>-NN` per unit, `G-NN` for global substrate. Work packages `WP-<NAME>` = one molecule.
- **Validation loop**: after each WP's DoD passes locally, run a peak-iteration validation pass on hard-to-verify atoms (verdict models, extractor evals, MTU harness, seed quality) — frontier via env key, results recorded in `docs/validation/`.

## 1 · Pinned contracts (C1–C7)

Implemented as zod schemas + pure functions in `packages/substrate/src/contracts/`, re-exported from `src/index.ts`, covered by `src/index.test.ts`. **Do not fork these shapes; extend via new versions.**

| Contract | Export | Shape (summary) | Owner → consumers |
|---|---|---|---|
| C1 Event log | `EventSchema`, `StoredEventSchema`, `canonicalJson`, `idempotencyKey` | 3 families (`stream`/`capture`/`narrative`), canonical JSON, `runId`, monotonic `seq`, unique `idempotencyKey`, sha-256 `chainHash` | 01 → all |
| C2 Decision record | `DecisionRecordSchema`, `GateVerdictSchema`, `gate()` | `decisionId, turnId, action, confidenceFeatures, verdict(execute\|escalate\|reject), outcome(nullable), confirmedAt(nullable)`; two-threshold gate fn | 01 → 02, 03 |
| C3 Retrieval verdict | `RetrievalVerdictSchema` | `kind(support\|contradict\|silent) + prob[0,1] + citedEvidence + claim` | 04 → 02, 01 |
| C4 Cost ledger | `StepRecordSchema`, `BudgetEventSchema`, `CacheEventSchema` | per-step, EXCLUSIVE token buckets (`inputTokens` excludes `cachedInputTokens`), `cacheEvent`, `latencyMs`, `promptFingerprint`, `qualitySignal`, join via `decisionId` | 03 ↔ 01 |
| C5 Confidence API | `ConfidenceRequestSchema`, `ConfidenceResponseSchema` | `POST /confidence → {score, band(execute-band\|escalation-band\|reject-band), explain, modelVersion}` | 02 → 01 (gate), 03 (tiering) |
| C6 Scenario | `ShockScenarioSchema`, `ShockInterventionSchema`, `WorldTemplate` | `id, name, realizedOutcome, window, seed, version, series`; intervention = `{profile, magnitude, channels, start}` | 05 → 01 (stress), 02 (worlds) |
| C7 Wire discipline | `PatchOpSchema` (RFC 6902), `RegistryEntrySchema`, `InstructionBlockSchema`, `DeltaPayloadSchema` | registry-driven versioned schemas; full payload turn 1, JSON-Patch deltas after; cache-stable instruction blocks | 03 → 01 render surface |

**Shared eval core** (`packages/substrate/src/eval.ts`): `brierScore`, `expectedCalibrationError`, `coverage`, `ndcgAtK` — the gate-as-eval, eval-as-gate primitives. Python equivalents per unit (scoringrules, uncertainty-toolbox) for heavy work.

## 2 · Port map (localhost, collision-free)

| Ports | Owner |
|---|---|
| 5432 pg · 6379 redis · 9000/9001 minio · 11434 ollama · 4000 litellm · 6006 phoenix · 2113 kurrent(v2) · 7233/7234/8233 temporal(v2) | shared G-atoms |
| 8930–8941 | Harness (api REST :8930, SSE :8931, WS :8932, gate :8934, escalations :8935, sandbox :8936, MCP :8937, hitl-dock :8938, uvx :8940, web :8941) |
| 8000–8060 | Trust (verifier :8010, retrieval-verdict :8011, schema-checker :8012, scorer :8020, ingest :8030, verifiability :8031, label-quality :8032, contamination :8033, diversity :8034, reconciler :8040, scheduler :8041, dashboards :8050/:8060) |
| 8100–8104 | Efficiency (ledger :8100, cache-analytics :8101, routing :8102, budget-gate :8103, escalation-monitor :8104) |
| 8201–8204 | Knowledge (characterize :8201, human-queue :8202, subgraph :8203, grounded-gate :8204) |
| 8300–8303 | Simulation (sim-api :8300, probes-human :8301, seed-synth :8302, simbench-runner :8303) |

## 3 · Global substrate atoms (G-01..G-10)

Built in Phase 0 (this commit or the immediate next):

| ID | Atom | Type | Tech | State |
|---|---|---|---|---|
| G-01 | `@substrate/substrate` contracts C1–C7 + eval core | lib | TS+zod | ✅ done (tests green) |
| G-02 | `@substrate/scenarios` shock seeds + interventions | lib/data | TS+JSON | ✅ done (tests green) |
| G-03 | root docker-compose (profiles per unit) | infra | compose | pending — each unit ships its own; root aggregates |
| G-04 | shared Postgres 17 | db | compose svc | per-unit DBs inside one instance |
| G-05 | shared Ollama | svc | compose / native | per-unit compose |
| G-06 | MinIO object store | db | compose svc | Trust/Simulation artifacts |
| G-07 | Redis (bus/locks) | db | compose svc | Knowledge bus, Trust locks |
| G-08 | Makefile | script | root targets | pending |
| G-09 | CI: golden + bench jobs | ci | GH Actions | pending |
| G-10 | uv workspace scaffolding (`py/`) | tooling | uv | pending (with each py unit) |

## 4 · Cross-ecosystem joints (the interlock)

```
01 decision log ──► 02 outcome-reconciler → recalibration loop   [C2 rows]
02 confidence ────► 01 gate verdicts + 03 tier thresholds         [C5 HTTP :8020]
04 verdicts ──────► 02 retrieval-verdict feature + 01 event log   [C3]
05 scenarios ─────► 01 stress-testing, 02 synthetic worlds        [C6 package]
03 ledger ────────► 02 token accounting, 01 budget-gate           [C4 :8100]
shared: C1-C7 contracts, wire registry + deltas (03), scenarios (G-02)
```

## 5 · Dispatch tree & sequencing

```
Me ── Phase 0 (contracts + PLAN.md + 5× BUILD.md, committed)
  ├── Subagent H → apps/01-harness/BUILD.md      (molecules WP-* in BUILD.md)
  ├── Subagent T → apps/02-trust/BUILD.md
  ├── Subagent E → apps/03-efficiency/BUILD.md
  ├── Subagent K → apps/04-knowledge/BUILD.md
  └── Subagent S → apps/05-simulation/BUILD.md
```

- All 5 subagents launch in parallel after Phase 0 commit. Sub-subagents handle one `WP-*` each, in parallel within a unit, respecting atom DAGs.
- **DoD per WP**: unit tests pass (`pnpm --filter <pkg> test` / `uv run pytest`), OpenAPI/README runbook written, acceptance mapping in the unit's BUILD.md, no v2 scope creep.
- After each WP: local validation; then peak-model validation pass where the WP's acceptance depends on model quality.

## 6 · Research corrections locked in (from landscape research)

- **Martian**: pivoted to interpretability — excluded. NotDiamond: cloud-only, benchmark reference only.
- **Kuzu**: archived Oct 2025 → **FalkorDB**. **Indexify**: unreachable → excluded.
- **"repe" / "Lumina"**: unverifiable → use **Min-K%Pro** + MinHash/n-gram + Patronus **Lynx/Glider/HHEM-2.1** ladder.
- **NVIDIA SynTool**: design reference only, not a dependency.
- **OTel GenAI semconv**: still settling — ledger aligns attribute names now, OTel export is v2.

## 7 · Acceptance map (per unit, = SPEC success signals)

| Unit | Headline acceptance |
|---|---|
| 01 | Golden-run replay byte-identical w/ zero re-rolls; mutation breaks CI. Gated-decision Pareto vs guardrails-only + turn-boundary HITL. Controlled-havoc recovers w/ zero double side effects. |
| 02 | ConfBench dominance curves (evidence vs self-report, under shift). Scorer injectable into 01; band tightens on real log. |
| 03 | ≥50% cost drop at equal outcomes, attributable in ledger. TCO predicts bill within margin. Delta protocol survives to turn 100. |
| 04 | Graph-vs-flat decision rule w/ data. Extraction error visible + decreasing; grounded gate catches a flat-index failure. |
| 05 | SimBench coverage 50/80/95 on 3 shocks (2025 = holdout). Hybrid partition measured. Presence vs turn-based measured on 5 probes. |
