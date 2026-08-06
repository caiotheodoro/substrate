# Research Agenda — Caio Theodoro

Five research units forming a small ecosystem around one conviction:

> **Agents fail in production not because the base model is wrong on average, but because a specific wrong decision ships undetected.**

Every unit is framed as a **verifiable research platform**: reference implementation + benchmark harness, so each claim can be measured against other methodologies — not asserted. Not research-for-its-own-sake, not a product plan: something you can run, benchmark, and falsify.

## The ecosystem

```
                     ┌─────────────────────────────┐
                     │ 01 HARNESS (the center)     │
                     │ deterministic · gated ·     │
                     │ replayable agent runtime    │
                     └───────┬─────────┬───────────┘
          feeds context      │         │        consumes
         ┌───────────────────┘         └───────────┐
         ▼                                       ▼
  04 KNOWLEDGE                          03 EFFICIENCY
  retrieval ops plane                    token & performance plane
         │                                       │
         │ evidence (support/contradiction)      │ wire/token discipline
         ▼                                       ▼
  02 TRUST  ←── outcome log & gated data ──→  feeds gates
  measurement plane
         ▲
         │ scenarios, synthetic worlds, calibration baselines
         └────────────────────────────────────────┘
  05 SIMULATION
```

## Unit map

| # | Unit | Core question | Verification core | Feeds / consumes |
|---|------|---------------|-------------------|------------------|
| 01 | **Harness** | What does a deterministic, gated, replayable agent runtime look like? | Golden-run replay suite; gated-decision benchmark; comparison vs turn-boundary HITL and ungated baselines | the substrate → all units |
| 02 | **Trust** | What does "confident and right" mean, and how do you gate the data that shapes it? | ConfBench; contamination/diversity gates vs ungated pipelines; recalibration measured on real decision streams | consumes 01's outcome log, 04's evidence, 05's synthetic worlds → feeds 01's gates |
| 03 | **Efficiency** | Which tokens carry information, and what is the cost of the wire? | Marginal-token-utility measurement; delta vs full-payload token accounting; cache-first vs baseline; latency budgets | consumes 01's ledger, 02's confidence → feeds 01's routing/cache discipline |
| 04 | **Knowledge** | How do you operate retrieval like a database? | GraphRAG-justification decision rule; extraction-error propagation; freshness economics; grounded-gate vs flat-index baseline | feeds 02's evidence, 01's context |
| 05 | **Simulation** | Can behavior — social and economic — be calibrated against reality? | SimBench retro-validation (coverage/Brier vs real shocks); believability probes vs turn-based baseline | feeds 02's synthetic worlds, 01's stress scenarios |

## Shared substrate

The units plug into each other through four shared artifacts, built once in the Harness:

1. **The event log** — every agent decision recorded with features, confidence, verdict, and (eventually) confirmed outcome. The compounding trust ledger (01, 02, 03).
2. **The eval harness** — offline evals and online gates sharing primitives, so a gate is a deployment of an eval and an eval is a gate in rehearsal (01, 02, 04).
3. **The wire discipline** — registry-driven, schema-validated, delta-based payloads; the same contract for UI, tool calls, and memory (01, 03).
4. **The scenario library** — historical shocks and synthetic worlds, reusable by simulation, stress-testing, and data generation (05 → 02, 01).

## Build order

**Phase 0 — substrate:** Harness (01) with event log, eval harness, wire discipline, golden-run replay.
**Phase 1 — measurement:** Trust (02) as the Harness's confidence core; Knowledge (04) as its context/evidence source.
**Phase 2 — efficiency:** Efficiency (03) riding the ledger and the confidence signal.
**Phase 3 — halo:** Simulation (05) generating scenarios, synthetic worlds, and calibration baselines that feed back into 01/02.

Units are designed to be built in parallel after Phase 0.

## Principles

- **Registry over generation.** When a structure can be enumerated, enumerate it. Generate only what must be novel.
- **Trust from outside the model's own weights.** Tool verification, retrieval support, schema checks, outcome logs — never self-report.
- **The gate is a P&L line, not a modeling choice.** Thresholds owned deliberately; the escalation band is a designed width.
- **The log compounds.** Every gated decision tightens future gates. This is the durable moat.
- **Token efficiency is an engineering property.** Cache hits, delta protocols, and token budgets are architecture, not afterthoughts.
- **Simulation for behavior; prediction for status quo.** And both must be calibrated against what actually happened.
- **Verifiable or nothing.** Every unit ships its benchmark harness; every claim is measured against a baseline.