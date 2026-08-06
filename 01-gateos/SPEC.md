# 01 · GateOS — The Decision-Gating Platform

## Thesis

Agent deployments do not die from average error. They die from the first undetected wrong decision shipped to a customer or a regulator. **GateOS is the runtime layer that decides, per decision, whether an agent action executes, escalates to a human, or is rejected — and grows more precise every day it runs.**

The model is not the product. The gate is.

## Why it matters

The 2025–2026 market flooding of agent platforms is producing demos that "work on average" and shut down the moment a single confidently-wrong action ships. The differentiation space has already moved past the base model (everyone has the same frontier APIs) into the reliability boundary around it. Nobody owns this boundary well. Most teams build agents with two states — it runs, or it doesn't compile. The three-state version — execute / escalate / reject — is the only version where "I don't know" is a legitimate output instead of a bug.

- **Execute** — confidence signal cleared the bar, action runs unsupervised.
- **Escalate** — signal ambiguous; a human reviews before anything happens (HITL done right: not "review everything", not "review nothing").
- **Reject** — signal bad enough that the action must not happen, no human required.

## Core concept

A gate is narrower than "evaluation":

| | Offline evaluation | Online gate |
|---|---|---|
| When | before a model ships | between proposal and execution |
| Unit | benchmark / aggregate score | one decision |
| Output | clear the bar / no | execute / escalate / reject |
| Feedback | next release | per-decision, compounding |

The gate lives at a boundary that is already instrumented in the agent runtime: **the point where a tool call is about to execute** — the natural MCP interception layer. It's the cheapest place to add a gate because permissioning and logging already exist there.

Two thresholds, not one. The gap between them is the escalation band, and its width is a decision made on purpose.

```
def gate(proposed_action, confidence_score, execute_threshold, reject_threshold):
    if confidence_score >= execute_threshold: return EXECUTE
    if confidence_score < reject_threshold: return REJECT
    return ESCALATE
```

### Guardrails are not gates

A guardrail is a category filter (PII, profanity, off-topic) — it doesn't reason about whether this particular decision is *correct*, only whether it's *allowed*.
A gate reasons per-decision. Two actions can both pass all guardrails and deserve different outcomes because one is the kind of claim the system has historically gotten right and the other isn't.

## What gets built

1. **MCP-boundary gate server** — intercepts tool calls, runs the gate, returns execute/escalate/reject, emits the full decision to the log.
2. **Confidence scoring interface** — pluggable scorer behind one interface (see ExEval / 02 for the scorer itself).
3. **Escalation queue as product surface** — reviewer UI showing proposed action, confidence, and context so a review takes seconds, not minutes. The escalation queue is not a debug log.
4. **Outcome reconciliation loop** — logs decisions paired with eventually-confirmed outcomes; feeds recalibration.
5. **Threshold manager** — surface execute/reject thresholds per agent, per decision class, owned by a product decision not a hyperparameter.

## Architecture sketch

```
Tool call → MCP boundary → gate(proposed_action, confidence)
                │
        ┌───────┼───────────┐
        ▼       ▼           ▼
     EXECUTE  ESCALATE    REJECT
                │
            queue UI ── human review ── permit/deny
                └──────────────┬───────────────┘
                               ▼
                     decision + outcome log   → recalibrate scorer
```

Decisions are event-sourced into the shared substrate; every record composes: proposed action, confidence features, gate verdict, and later the confirmed outcome.

## The compounding moat

Every gated decision produces a labeled record that only exists because the system ran in production. Competitors can license the same base model. They can copy the architecture from a conference talk. They cannot copy six months of gated decisions paired with real outcomes.

The loop closes only if outcomes get confirmed and fed back:

```
log_and_recalibrate(decision_log, scorer, retrain_every_n):
    if len(decision_log) % retrain_every_n == 0:
        labeled = [(d.features, d.confirmed_outcome) for d in decision_log if d.confirmed_outcome is not None]
        scorer.fit(labeled)
```

A gate that logs but never reconciles against what actually happened is a dashboard, not a gate.

## Open research questions

- **Threshold dynamics.** How do optimal thresholds drift as agents, models, or workloads change? Is there a stable, live-updating estimator for optimal threshold from the outcome stream?
- **Feature space.** Which decision features actually predict human-reversal and blown outcomes? See 02.
- **Delayed reward.** Most outcomes arrive late (a financial transaction settles in T+N, a support ticket closes in 3 days). What is the right reconciliation horizon, and how do we backfill the scorer with partial feedback?
- **Policy v deterministic.** Where does a policy engine (registry-pinned rules) belong relative to a gate? (Adopt AI's policy-engine work is the prehistory of this design.)

## Prior work it builds on

- Adopt AI HITL system: signal-driven resolve state machine, optimistic locking, tenant isolation, 3-action resolution, Temporal signal contract.
- Adopt AI policy engine: policy-version pinning, audit logging.
- Blog: *Evaluation Gates Are the Reliability Moat* (exact 3-state function, threshold P&L framing, confidence-scoring fallacy, log compound).
- Skills: agent orchestration, HITL systems, confidence scoring, Temporal, structured outputs, LangSmith/Langfuse observability.

## Risks / failure modes

- **Escalation collapse.** Thresholds set too tightly → reviewer queue becomes the bottleneck → gates abandoned. Mitigate: threshold manager + queue throughput telemetry.
- **No outcome signal.** If outcomes can't be reconciled (workflows without feedback), log becomes dashboard. Mitigate: design partial-confirmation sources into targets.
- **Gate theatre** — teams adopting it for compliance without acting on the signal. Mitigate: the recalibration loop automation makes the platform's value visible.

## Success signals

- A reference workload where escalation rate and error rate are reported as a Pareto curve, and the team is seen moving along it deliberately.
- Decision log endpoints.* Outcome-confirmed dataset that measurably tightens escalation band over time (-X% escalation without increasing → negative outcome rate).
- Reusable open protocol for "gated decision" event schema adopted beyond one codebase.