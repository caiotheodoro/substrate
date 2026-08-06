# 03 · CostOS — Cost as a First-Class Architecture Property

## Thesis

Model and serving choices are treated as a quality decision and discovered to be a pricing decision once the bill arrives. **CostOS treats cost as architecture**: batching, quantization, tiering, caching, and provider routing become explicit, observable layers of the serving stack — with the same rigor as reliability.

The bill is not an afterthought. The bill is a design input.

## Why it matters

Every agent workload in production has a cost curve that is decided before anyone looks at the invoice: prompt sizes (dashboards, tool schemas, context stuffing), cache hit rates, model tier per step, quantization, provider routing. Teams discover cost as a *failure mode* ("why is this demo costing $40k/month?") instead of a *design parameter*. The 2026 market is full of agent frameworks that optimize quality and ignore the cost layer — the result is that production agents that do real work at volume quietly stop being viable. Cost engineering is where infrastructure people and AI engineers actually meet.

## Core concept

The serving stack has distinct cost levers, each with a quality/cost tradeoff surface that is *measurable and archivable*:

| Layer | Lever | Tradeoff surface |
|---|---|---|
| Context | prompt caching, 6-layer token optimization, tool-schema trimming | cache hit rate ↑, prompt size ↓ vs quality drift |
| Inference | batching, quantization (INT8/FP8), speculative decoding, vLLM | throughput ↑, latency ↑ per token, quality drift on quantized weights |
| Tiering | model routing per step (small vs frontier), escalation to big model | cost ↓ vs failure rate ↑ on hard steps |
| Provider | multi-provider routing (Bedrock, OpenAI, open models), region/price arbitrage | latency/cost per unit quality |
| Self-host | owning weights vs API | CapEx + ops vs unit cost at volume |

**The key insight: these are not independent.** Cache hit rate changes the marginal cost of tiering; quantization changes which tasks a small model can do; prompt size changes cache viability. CostOS is the layer that makes these interactions *visible and tunable as one system*.

## What gets built

1. **Cost instrumentation layer** — token-accounted, per-step, per-agent cost attribution. Not an invoice dump: a ledger with the same granularity as the decision log (01). Every agent step records model, tokens, cache status, quantization, provider, latency, quality signal.
2. **Cache analytics** — what prompts/contexts hit the cache, what misses, what the hit rate *would be* if tool schemas and system prompts were structured for reuse (see 07 GenUI-Wire's 6-layer token optimization as prior art).
3. **Routing controller** — a rule/ML policy that assigns each step a (model, provider, quantization) tuple, with the same threshold-as-P&L framing as GateOS: escalate to a bigger model exactly when the cheap path's confidence is low (pairs with 02 ExEval's confidence as the *cost-routing signal*).
4. **TCO model** — a transparent calculator mapping workloads → cost curves across the lever grid, so "self-host vs API" is a real decision, not a vibe.
5. **Cost gates** — per-workload cost budgets with the same execute/escalate/reject structure as GateOS (a step that would blow the weekly budget is a *decision*, not a surprise).

## Architecture sketch

```
agent step
   ├─ prompt optimizer (cache-friendly structure)
   ├─ routing policy → (model, provider, quantization)
   ├─ serving (vLLM / provider) → tokens, cache hit, latency
   └─ quality signal (02 confidence / gate verdict)
              ▼
     cost ledger (per-step, attributed)
              ▼
     cache analytics + routing policy retrain + TCO reports
```

Routing and quality are coupled on purpose: the routing policy consumes the ExEval confidence signal, and the quality signal consumes the gate verdict — cost optimization never runs blind to correctness.

## Research program

- **R1: The prompt-optimization quality surface.** Quantify quality drift vs token reduction for systematic context-slimming (tool schemas, examples, system prompts) across task families. Hypothesis: most workloads have a 60–80% token reduction with <1% quality drift — but the drift is *task-dependent*, and the safe zone is discoverable automatically.
- **R2: Cache-first agent design.** Which agent architectures (static schemas, registry-driven payloads, stable instruction blocks) maximize cache hit rates? What's the measured hit-rate ceiling in real workloads, and what does it do to marginal cost?
- **R3: Confidence-driven tiering.** With ExEval as the routing signal, how much cost drops when small models handle the confidently-easy steps and big models handle the rest, at equal outcome rates?
- **R4: Quantization honesty.** INT8/FP8 serving quality degradation *measured at the gate* (not perplexity) — which workloads survive quantization, which don't, and how the gate verdict changes with it.

## Prior work it builds on

- Blog: *The Economics of Model Serving* (batching, quantization, tiering, self-host bet as cost decisions), *Structured Outputs* (constraint as token savings).
- Adopt AI: 6-layer token-optimization scheme (dashboard prompts ≈15k → 700–2k tokens), JSON-Patch delta protocol (90% token savings on follow-ups), AWS Bedrock multi-model inference behind a unified selection interface with provider routing and caching.
- Skills: model serving (vLLM), quantization, prompt caching, context engineering, model selection, AWS Bedrock, observability.

## Risks / failure modes

- **Optimizing the wrong unit.** Token cost is not total cost; latency, ops, and engineering complexity often dominate. TCO model must stay honest about non-token costs or the whole system loses credibility.
- **Cache myopia.** Chasing hit rates can push teams to freeze prompts that should evolve. Cache analytics must distinguish *reuse-by-design* from *stagnation*.
- **Tiering cascade.** Aggressive small-model routing increases escalation load on the big model path and on humans. The coupling to gates (01) is what keeps this honest.

## Success signals

- A reference workload where cost per completed task drops ≥50% at equal (or better) outcome rates, with the attribution ledger showing exactly why.
- The TCO model correctly predicting the observed bill to within a stated margin across two different workloads.
- Routing policy + cost gates running in production, with cost budgets surfacing as first-class decisions rather than invoice surprises.
