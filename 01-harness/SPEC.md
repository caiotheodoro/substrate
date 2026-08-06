# 01 · Harness — The Deterministic, Gated, Replayable Agent Runtime

## Thesis

Agents fail in production not because the base model is wrong on average, but because a specific wrong decision ships undetected. The runtime that runs an agent is where trust is decided: it must record everything, decide nothing blindly, and be able to prove what happened.

**Harness is a reference agent runtime whose three load-bearing properties are determinism, gating, and replay — each implemented as a verifiable primitive, and each measured against the industry's default approach.** It is not a product. It is a benchmarkable substrate: the thing every other unit in this ecosystem plugs into, and the thing that lets claims about "trustworthy agents" be tested instead of asserted.

## Why it matters

The 2026 agent stack has a gap between demo and production. Demo agents have two states: it runs, or it doesn't compile. Production agents need a third: *I don't know* — and a system capable of acting on it (escalate to a human, or refuse). The industry default is to bolt trust on after the fact: a chat log, a guardrail, a review queue that nobody designed as a system.

The production system this spec is grounded on learned this the expensive way over multiple incidents: a separate `capture`/`render` two-source-of-truth model, a validation-retry loop instead of silent blank renders, a confidence+required-fields gate instead of "always pause", a sandbox lease alive only while work is active, a tool-loop with real batching discipline. Those are not product features — they are **design constraints** any serious agent runtime must satisfy. This spec makes them first principles, and then benchmarks them.

## Core concept

### Three-state gating as a runtime primitive

A gate is narrower than an evaluation. Offline evaluation decides whether a model ships; a gate decides, per decision, whether this action executes:

```
def gate(proposed_action, confidence, execute_threshold, reject_threshold):
    if confidence >= execute_threshold: return EXECUTE
    if confidence < reject_threshold:   return REJECT
    return ESCALATE
```

Two thresholds, not one. The band between them is the escalation band — a designed cost/risk curve, owned deliberately, not a framework default. The gate lives at the MCP boundary (the point where a tool call is about to execute), because that boundary is already instrumented for permissioning and logging.

### Capture/render split — the two-source-of-truth invariant

- **Capture**: everything that actually happened (every tool call, full args, stdout, exit code, timestamps) — append-only, **never flag-gated**. This is ground truth.
- **Render**: what the LLM *says* happened (plan, phases, chips, reflections) — a projection, LLM-authored, only affects display.

This invariant is what makes audit, replay, and post-hoc traceability possible at all. The transcript is the trust ledger; the UI is a view. Built once, never re-litigated.

### Replay-safe execution

Every run is a stream of events; run state is a pure fold of the event stream. Idempotency keys make replay safe (tool results are replayed, not re-executed). This is the only way to answer "what happened, in order, with the same inputs" on demand — the enterprise gatekeeper for autonomy.

## Ecosystem role

- **The substrate.** Event log, eval harness, wire discipline, and scenario library live here once and are consumed by every other unit.
- **To 02 Trust:** harness emits the `decision log` (features + confidence + verdict + outcome) that Trust's recalibration loop and its gated-data pipelines depend on.
- **To 03 Efficiency:** harness records the `cost ledger` (per-step tokens, cache status, latency, model, provider) on every decision.
- **To 04 Knowledge:** harness consumes retrieval context; every retrieval feeding a decision passes the grounded-gate verdict (support/contradict/silent) into the event log.
- **To 05 Simulation:** harness runs the *scenario stress-test* — replaying injected shocks against its gates to measure how gating behaves under distribution shift.

## What gets built — the reference implementation and its benchmarks

1. **Turn-scoped Temporal workflow + bound loop with batching discipline.** Short-lived per-turn workflows (bounded history, per-turn crash blast radius), bounded tool iteration with a hard cap, and narrative+work batched into the SAME response so bookkeeping never eats the loop.
2. **Event-sourced run engine.** 3-family event model (`stream` / `capture` / `narrative`), append-only transcript, replay-mode with side-effect suppression, idempotency layer. This is the golden-run source of truth.
3. **Gate server at the MCP boundary.** 3-state verdict, escalation queue as a first-class surface (proposal + confidence + context so a review takes seconds), threshold manager, veto records back into the event log.
4. **Unified `pending_action` HITL primitive.** One tool (`request_action(kind: question|form|decision, ...)`) replaces ad-hoc builder decks; all pending actions resolve in one dock with an all-ready gate and atomic submit. True mid-turn pause/resume via Temporal signals (`wait_condition`), not a new-turn workaround.
5. **Sandbox discipline.** Reusable-but-cheap sandbox: short lease, keepalive only while a turn is active, liveness probe, bounded I/O timeouts, parallel artifact upload that never gates the "done" signal.
6. **Golden-run test harness.** CI runs every change against recorded runs — same inputs, same events, snapshot the run; a change that alters the event stream of a golden run fails CI.

### Benchmark deliverables (the verifiable core)

- **Golden-run replay suite** — a corpus of runs is replayed event-exactly, asserting byte-identical event streams. This is the falsification core for "is the runtime deterministic."
- **Gated-decision benchmark** — a task suite with ground truth, scored on: escalation rate, blown-outcome rate (decisions that looked fine but were wrong), and the escalation/error Pareto that the threshold manager must navigate. Comparison against **two baselines**: (a) turn-boundary-only HITL (the industry default), (b) guardrails-only (no per-decision gate).
- **Controlled-havoc benchmark** — the forced-incident suite: injected failures (duplicate tool call, unresponsive sandbox, mid-run crash), asserting the runtime recovers to a repeatable state (idempotency, checkpoint/restore).

## Architecture sketch

```
Client  ⇄  Harness API (SSE) ⇄ orchestrator (turn workflow, Temporal)
                                │ LLM ↔ tool-loop (bounded, batched)
                                │   │
                                │   └─ MCP boundary ── gate 3-state
                                │          │
                          EXECUTE/ESCALATE/REJECT
                                │          │
                                ▼          ▼
                        side effects   reviewer surface (pending_action)
                                │
                                ▼
                      event log (capture, never gated) ──► replay / audit / benchmarks
```

## Deep methodology

- **Non-determinism taxonomy as spec, not bug.** LLM calls are stochastic, tool results external, time passes, humans intervene. The runtime *records each* (recorded response vs re-roll vs flag) and these become replay principles.
- **Validation-retry loop.** Backend-authoritative schema validation on every payload; the LLM self-corrects on return so malformed payloads never reach the render path. The "no silent blank UI" rule, enforced at the boundary.
- **Batching discipline as a design constraint.** Narrative and work tools emit in the SAME response; bookkeeping never eats the tool loop.

## Research program

- **R1: Stochastic-replay semantics.** Which non-determinism sources can be made *recorder-deterministic* vs require re-roll? Where does replay stop being exact and start being "semantically equal"? Enumerate, spec, prototype.
- **R2: The escalation/error frontier.** What does the Pareto look like — the optimal threshold set as a function of task structure? Is there a stable, live-updating estimator from the outcome stream (ties to 02)?
- **R3: Validation-retry effectiveness.** What is the actual recovery rate of LLM self-correction per failure class (schema vs guardrail vs gate)?
- **R4: Sandbox lease economics.** How cheap can a persistent-but-cheap sandbox go — lease length, keepalive cost, liveness probe robustness?
- **R5: Mid-turn pause/resume.** Temporal-signal pause vs new-turn workaround: does the agent's tool history and in-flight sandbox state survive across a real pause? Measurable UX + correctness delta.

## Risks / failure modes

- **Replay theater.** If replay silently re-rolls LLM calls instead of recording them, the audit is fiction — the recorded-response discipline is non-negotiable.
- **Gate collapse.** Thresholds tuned to make the demo pass → escalation overload or dangerous "always execute." The benchmark's Pareto axes keep this honest.
- **The runtime burden.** A full runtime is a big engineering surface for a research agenda; the harness gets built **small-first** (Postgres-backed v1) with Temporal as fast-follow, and the *benchmark coroutine*, gold replays, and gate core are the parts worth public release even before the surface is finished.
- **Baseline fairness.** Comparison against ungated baselines must control for the same task distribution, or the gate's wins are artifacts.

## Success signals

- Golden-run replay suite: byte-identical replays with zero re-rolls on a reference corpus; a mutation in the harness code breaks the golden snapshot.
- Gated-decision benchmark: measurable reduction in blown-outcome rate vs a guardrail-only baseline at equal escape rate, with the Pareto shown, not claimed.
- **Controlled-havoc recovery:** forced-incident runs recover to a repeatable state with zero double side effects.
- **An external reproduction:** someone outside this repo reproduces the gated-decision benchmark's headline numbers against the same baselines.