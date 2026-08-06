# Research Agenda — Caio Theodoro

Ten research and product tracks exploring the current edge of AI engineering. Written as specs so each can be executed independently or as part of the shared substrate defined below.

Guiding conviction: **agents fail in production not because the base model is wrong on average, but because a specific wrong decision ships undetected.** Everything here is a consequence of that conviction.

- The model is not the differentiator. The gate around it is.
- Trust must come from outside the model's own weights (tool verification, retrieval support, schema checks, outcome logs) — never from self-report.
- Cost is a first-class architecture property, not an afterthought of the bill.
- Determinism, replay, and audit are the price of autonomy.
- Simulation is the honest tool for behavior; prediction is for what stays static.
- The wire format and the registry are the product, not the prompt.

---

## The shared substrate

Most tracks build on the same core pieces. Building these first unblocks everything else:

1. **Temporal-based orchestration with replay-safe semantics** — the deterministic runtime substrate (used by 01, 06, 07, 08).
2. **A decision log** — every agent decision recorded with features, confidence, action, and (eventually) outcome. The compounding asset (01, 02, 05, 09).
3. **An eval harness** — offline evals + online gates, sharing primitives (01, 02, 04, 09).
4. **The MCP boundary** — the natural instrumentation point where tool calls can be gated, logged, and verified (01, 02, 06, 07).

---

## Track map

| # | Track | Type | Core question | Feeds / depends on |
|---|-------|------|---------------|--------------------|
| 01 | GateOS | Platform | How do you gate every decision in production? | substrate → everything |
| 02 | ExEval | Research / Model | What does "confident and right" actually mean? | 01 confidence core |
| 03 | CostOS | Research / Tooling | Which layer of the serving stack is the pricing decision? | 01, 02, 07 |
| 04 | GraphOps | Platform | What does it take to operate a GraphRAG? | 02 retrieval evidence, 01 gating |
| 05 | SimBench | Research / Library | Can behavior be calibrated against history? | 02 calibration, 10 behavior |
| 06 | TabbyOS | Platform | How do agents get real sessions without stealing credentials? | 01 gating, substrate |
| 07 | GenUI-Wire | Protocol | What is the wire format of generated UI? | 01 gating, substrate, 03 costs |
| 08 | Replay | Research / Runtime | What makes an agent run replayable? | substrate → all autonomous tracks |
| 09 | SynthGate | Research / Data | How do you gate the data that shapes the model? | 02 evals, 02, 01 gates |
| 10 | Presence | Research | What makes agents feel like people? | 05 simulation, 02 |

---

## Suggested build order

**Phase 0 — substrate first: 08 Replay + decision log + eval harness + MCP boundary.**
**Phase 1 — GateOS (01) on the substrate, with ExEval (02) as its confidence core.**
**Phase 2 — bolt-on modules: CostOS (03), TabbyOS (06), GenUI-Wire (07).**
**Phase 3 — research halo: GraphOps (04), SimBench (05), SynthGate (09), Presence (10).**

Everything is designed to be built in parallel after Phase 1.

---

## Principles

- **Registry over generation.** When a structure can be enumerated, enumerate it. Generate only what must be novel.
- **Structured outputs are a trust layer, not a nice-to-have.** The trust boundary moves to inference.
- **The gate is a P&L line, not a modeling choice.** Thresholds are owned by a product decision, not a hyperparameter.
- **The log compounds.** Every gated decision produces a labeled outcome record that tightens future gates. This is the durable moat.
- **Cost is architecture.** Batching, quantization, tiering, caching decide the economics before the bill arrives.
- **Simulation for behavior; prediction for status quo.** Fit curves only where the system is static.

---

## Contributions

This is a personal research agenda. Each SPEC.md captures a self-contained research or product direction with honest accounting of open questions and failure modes — no monetization framing, value and impact only.