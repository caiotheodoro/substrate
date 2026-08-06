# @substrate/harness

**The deterministic, gated, replayable agent runtime** — the center of the ecosystem.

Every unit in this agenda plugs into this one. It records everything, decides nothing blindly, and can prove what happened.

## What it is

A reference agent runtime whose three load-bearing properties are each a verifiable primitive:

- **Determinism** — turn-scoped durable workflows, capture/render split (the transcript is the trust ledger; the UI is a view), replay-safe execution with idempotency keys.
- **Gating** — a 3-state gate at the MCP boundary: `execute` / `escalate` / `reject`. Two thresholds, the escalation band between them a designed cost/risk curve.
- **Replay** — an event-sourced run engine and golden-run CI, so "what happened, in order, with the same inputs" is answered byte-for-byte.

## Benchmarks (the verifiable core)

- **Golden-run replay suite** — byte-identical replays; a harness mutation breaks the snapshot.
- **Gated-decision benchmark** — escalation rate vs blown-outcome-rate Pareto, against a turn-boundary-HITL baseline and a guardrails-only baseline.
- **Controlled-havoc suite** — forced incidents (duplicate tool call, dead sandbox, mid-run crash) assert recovery with zero double side effects.

## Ecosystem

- Feeds the event log to `trust` (recalibration + gated data), the cost ledger to `efficiency`, retrieval evidence to `knowledge`, and consumes `simulation`'s stress scenarios.
- Consumes `@substrate/substrate` (event types, eval harness, wire schemas) and `@substrate/scenarios`.

## State

Implemented. Golden-corpus replay is byte-identical (idempotency keys,
canonical prompts); the gate consumes trust's confidence over HTTP (C5)
with an offline heuristic fallback; the budget gate and cost ledger wire
into efficiency (C4); the seam e2e drives one decision through all four
units with real services. 78 tests.