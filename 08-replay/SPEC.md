# 08 · Replay — The Deterministic Runtime Behind Trustworthy Agents

## Thesis

The only way to trust an agent that acts autonomously is to be able to **replay it** — to re-run the exact sequence of observations, decisions, and tool calls that produced an action, and prove that what you see in the audit log is what actually happened. Most agent frameworks can't do this: runs are loops with side effects, idempotency is a hope, and the audit trail is prose.

**Replay is the event-sourced, replay-safe agent runtime — the substrate that makes autonomy auditable.** It is the shared foundation of everything on this agenda (01 gates, 06 sessions, 07 UI generation) and the layer where "trust the agent" stops being a vibe and becomes an engineering property.

## Why it matters

- **Autonomy without audit is a lawsuit waiting for a customer.** Enterprises will not let agents spend money, send messages, or mutate records until they can prove what happened, in order, with the same inputs, on demand. The enterprise gatekeeper for agents is the audit trail, not the model quality.
- **Reproducibility is the scientific method of AI ops.** If a bad decision ships, you need to re-run it, understand it, and prove the fix. Without replay, the "postmortem" is a chat log and a guess.
- **It's the base layer** — the gating (01), confidence (02), and cost (03) layers all operate *on* a runtime that must already be replayable.

## Core concept

### Event sourcing for agent runs

Every agent run is a stream of **events**: observation received, decision made (with the confidence signal), tool call initiated, tool result returned, action taken, escalation raised. The run state is a pure function of the event stream. Replaying = re-apply events to a state store, deterministically.

```
run = fold(events, state)
```

The runtime is a **state machine per turn** — the same discipline as the Adopt HITL resolve state machine (optimistic locking, tenant isolation, 3-action resolution) applied to the whole run.

### Idempotency as semantics, not hope

Every tool call carries an idempotency key. Replayed runs do not re-execute side effects — they *replay their recorded results*. The distinction:

- **Re-run** (new run, same goal) — fresh execution, new idempotency keys.
- **Replay** (audit/reproduce) — event stream re-applied, tool results from the log, zero side effects.
- **Resume** (crash recovery) — events up to the checkpoint re-applied, execution continues from the last *committed* event.

### Checkpointing & restore

The runtime snapshots state at committed event boundaries. A crash resumes from the last snapshot + unapplied events. No lost turns, no double effects.

### Temporal as the orchestrator

Temporal workflows give durable execution (activity retries, signal handling, sagas). Replay adds the *event log discipline* on top: Temporal's `workflow.Sleep` and `workflow.GetSignal` are recorded as events, so even *time* and *human input* are replayable.

## What gets built

1. **Event schema** — the canonical, versioned event type set (observation, decision, tool_call, tool_result, action, escalation, signal). Interop with the 01 decision log.
2. **Replay engine** — event-store-backed run execution; fold-to-state; replay mode with side-effect suppression.
3. **Idempotency layer** — key generation, dedupe, tool-result caching, and the "replay does not re-execute" guarantee.
4. **Checkpoint/restore** — snapshot store, crash resume, temporal integration (or standalone for non-Temporal frameworks).
5. **Audit server** — the product surface: view a run as its event stream, diff two runs, replay into a sandbox, export compliance-grade trails (what was decided, with what confidence, by which version of which policy — pins from the 01 policy engine).
6. **Deterministic test harness** — runs in CI: same inputs → same events → snapshot the whole run as a golden test.

## Architecture sketch

```
                 agent turn
                    │
    ┌───────────────┼──────────────────┐
    ▼               ▼                  ▼
 observation  decision(conf  tool_call(idem-key)
    │           |score)          └→ result recorded
    └─────►  event store (append-only, versioned)
                    │
                    ├─► fold → run state (pure)
                    ├─► checkpoint/snapshot
                    └─► audit server: replay, diff, export
```

## Research program

- **R1: The granularity question.** Where are the event boundaries? Too coarse = audit gaps; too fine = event store explodes. What's the right "decision unit" for a useful audit trail (paired with 01's decision definition)?
- **R2: Non-determinism taxonomy.** LLM calls are stochastic, tool results are external, time passes, humans intervene. Enumerate the nondeterminism sources and the replay *semantics* for each (recorded LLM response? re-roll? flag?). This is the deep research — "replay" for stochastic systems is a design question, not a feature.
- **R3: The compression boundary.** Event streams for long-running agents get huge. Where can events be compacted (decision logs retained, raw token payloads pruned) without losing auditability? Retention policy as product.
- **R4: Cross-run proof.** Given an event stream and a policy-version pin, can you *prove* a run complied without re-executing? (This is the compliance-native claim — pairs with 01 policy engine pinning.)

## Prior work it builds on

- Adopt: Temporal orchestration, replay-safe semantics, HITL resolve state machine with optimistic locking, policy version pinning, the deterministic runtime substrate (explicitly named in the CV as the substrate every capability runs on).
- Skills: Temporal workflows, event-driven architecture, idempotency, observability, structured outputs, HITL.

## Risks / failure modes

- **The stochastic replay lie.** If replay silently re-rolls LLM calls instead of recording them, the "audit trail" is fiction. The recorded-response discipline must be the non-negotiable default.
- **Event-store gravity.** Append-only logs grow unbounded; without compression/retention as a designed feature, the store becomes the thing that doesn't scale.
- **Over-engineering the audit.** The compliance-trail surface can become a museum nobody reads; pair it with the live decisions (01) so the audit is *used*, not just kept.

## Success signals

- A run with a known bad decision is replayed into a sandbox, the exact event sequence shown, and the fix verified by re-running the same event stream with a new policy pin.
- Crash-resume in production: a mid-run failure restores from checkpoint with zero double side effects.
- CI harness: every agent change ships with golden-run snapshots; a change that alters the event stream of a golden run fails CI.
- An exported audit trail that a compliance reviewer can follow end-to-end without asking a single clarifying question.