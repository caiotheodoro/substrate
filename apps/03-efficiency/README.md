# @substrate/efficiency

**Token economics and performance engineering.** The question nobody has answered properly: *which tokens carry information, and what is the cost of the wire between the model and everything around it?*

## What it is

Cost as a first-class architecture property. A measured answer to "how fat is your prompt?" — ground truth by task, not by vibes:

- **Marginal token utility** — which prompt regions (system, tool schemas, few-shot, dynamic context) actually change output.
- **Wire discipline** — registry-driven, schema-validated, delta-based payloads (JSON-Patch follow-ups ≈90% token savings; compact streaming DSLs ≈67% vs JSON).
- **Cost ledger** — per-step token/cost/latency/cache attribution, joinable to the Harness's decision log.
- **Latency budgets** — bounded I/O timeouts, parallelized artifact upload, batched bookkeeping, heartbeats.

## Benchmarks

- **Marginal-token-utility harness** — token buckets ranked by contribution, task-family split.
- **Delta-protocol economics** — does the 90% follow-up claim survive the 100th turn?
- **Confidence-driven tiering** — cost drop at equal outcome rates when the Trust signal routes small models to easy steps.
- **TCO model** — workload → cost curves, honest about non-token costs.

## Ecosystem

- Consumes the Harness's cost ledger and Trust's confidence signal.
- Feeds routing policy, token-budget enforcement, and wire discipline back to the Harness.

## State

Spec written (`SPEC.md`). No implementation yet.