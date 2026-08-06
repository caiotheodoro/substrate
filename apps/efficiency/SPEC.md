# 03 · Efficiency — Token Economics and Performance Engineering

## Thesis

Model and serving choices are treated as a quality decision and discovered to be a pricing decision once the bill arrives. Prompt sizes drift, cache hit rates go unwatched, small models are routed by instinct, and latency is a backlog item rather than a design constraint.

**Efficiency is the study of where information actually lives in an agent workload — and the engineering discipline that makes token cost, latency, and cache behavior measurable, attributable, and tunable as one system.** The underlying question is the one nobody has answered properly: *which tokens carry information, and what is the cost of the wire between the model and everything around it?*

## Why it matters

Agent workloads have a cost curve that is decided before anyone looks at the invoice: prompt size (full schemas, bloated context), cache hit rate, model tier per step, quantization, provider routing. Teams discover cost as a *failure mode* ("why is this $40k/month?") instead of a *design parameter*. And because the layers interact — cache hit rate changes the marginal cost of tiering; quantization changes what a small model can do; prompt size changes cache viability — the only way to control it is to make it **one observable system**.

The measured, production-proven anchors this spec builds on:
- A dashboard prompt optimized from ≈15k → 700–2k tokens by a 6-layer scheme.
- A JSON-Patch delta protocol cutting follow-up UI edits by ~90% in tokens.
- A compact streaming UI language (OpenUI) cutting payloads by ~67% vs JSON.
- Cache-friendly prompt architecture as a first-class design, not an afterthought.

These are not tips. They are evidence that **wire discipline is architecture** — and that there is a measurement surface waiting to be standardized.

## Core concept

### The token-utility question

The interesting research space is not "reduce tokens" but **"which tokens carry information?"** A marginal-token-utility study: across task families, fraction of tokens in system prompts, tool schemas, few-shot examples, and dynamic context that actually change the output. This is the foundation — a measured answer to "how fat is your prompt?" that ground truth by task, not by vibes.

### Wire as a first-class artifact

The wire between model and environment — tool schemas, generated UI payloads, memory, retrieval results — is where most "waste" lives, and where regeneration and caching are decided. Registry-driven, schema-validated, delta-based payloads (the GenUI insight) are token economics applied to the wire: versioned schemas against a finite registry, full payload on first turn, JSON-Patch deltas on follow-ups, cache-friendly stable blocks.

### The cost ledger as truth

Every agent step records: model, tokens in/out, cache hit/miss, quantization, provider, latency, quality signal. This is the attribution layer — the same grain as the decision log (01) — without which "tune your thresholds" is astrology.

### Latency as a property, not a backlog

Bounded I/O timeouts on every external call, parallelized artifact upload that never gates "done", batching narrative annotations into the same response as work (no extra round-trips), heartbeats on long operations, and correct sizing of the execution environment. These are the documented latency-rescues from a production harness (01) — treated as design constraints, not lessons to re-learn.

## Ecosystem role

- **Consumes from 01:** the cost ledger per step, latency data, cache events.
- **Consumes from 02:** the confidence signal — the routing gate for "small model allowed here."
- **Feeds to 01:** the token-budget enforcement (a step that would blow a budget is *a decision*, handled by the gate), the routing policy, and the wire discipline (delta/registry protocols used by the harness's render surface).
- **Feeds to 02:** token accounting for eval and gate costs, so Trust knows what reliability costs.

## What gets built

1. **The cost ledger + attribution** — per-step token and cost accounting, the same granularity as the decision log, joinable to it.
2. **Cache analytics** — which prompts hit, what misses, what the hit rate *would be* if system prompts and schemas were structured for reuse.
3. **Routing controller** — a small policy that assigns each step a (model, provider, quantization) tuple. Confidence-gated tiering: cheap model on confident-easy steps, reserve the frontier for hard ones.
4. **Wire discipline library + toy `render_ui` / tool-schema reduction** — the registry-driven schemas, delta protocol, cache-friendly instruction blocks.
5. **Marginal-token-utility harness** — the benchmark that isolates which prompt regions carry information, task family by task family.
6. **TCO model** — workload → cost curves across the lever grid, honest about non-token costs (latency, ops).

## Architecture sketch

```
agent step
   ├─ prompt optimizer (cache-friendly structure)
   ├─ routing policy → (model, provider, quantization)
   ├─ serving → tokens, cache hit, latency
   └─ quality signal (02 confidence / gate verdict)
              ▼
     cost ledger (per-step, attributed, joinable to decision log)
              ▼
     cache analytics + routing retrain + marginal-token-utility output
```

## Research program

- **R1: Marginal token utility.** Which token fixed regions (system, tool schemas, few-shot, dynamic context) actually change output, measured task-family by task-family? This is a benchmark, not an essay — the "which tokens matter" answer, quantified.
- **R2: Cache-first agent design.** What is the measured hit-rate ceiling for registry-driven payloads and stable instruction blocks, and what does it do to marginal cost?
- **R3: Confidence-driven tiering.** With 02's confidence as routing signal, how much cost drops when small models handle the confidently-easy steps at equal outcomes?
- **R4: Delta protocol economics.** The JSON-Patch follow-up savings at the 100th turn of a session — does the 90% claim survive scale? Where does a "squash to full state" become cheaper than continuing patches?
- **R5: Quantization honesty.** INT8/FP8 degradation measured *at the gate* (not perplexity) — which workloads survive quantization, which don't.

## Risks / failure modes

- **Optimizing the wrong unit.** Token cost is not total cost — latency, ops, and engineering dominate. The TCO model stays honest about non-token costs.
- **Cache myopia.** Chasing hit rates can freeze prompts that should evolve. Cache analytics must distinguish reuse-by-design from stagnation.
- **The tiering cascade.** Aggressive small-model routing increases escalation load; the coupling to 02's confidence and 01's gates is what keeps this honest.
- **Micro-optimization debt.** A thicket of token-optimized surfaces can hide bugs; the delta protocols need golden tests too.

## Success signals

- Marginal-token-utility study produced: token buckets rank by contribution, task-family-split, an honest "which part of your prompt pays for itself."
- Cost per completed task drops ≥50% at equal outcome rates on a reference workload, attributable in the ledger.
- The TCO model predicts observed bill within a stated margin across two workloads.
- The cache-first/routing/caching stack holds at reference latency budgets, not just token budgets.