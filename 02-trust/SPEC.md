# 02 · Trust — One Measurement Discipline for Actions and Data

## Thesis

A model's own token probabilities and self-consistency checks measure how sure a model is **of itself** — not whether it is right. A model that is confidently and consistently wrong passes every self-check. Trust cannot be built on self-report, and it cannot be achieved once: the same discipline that gates an action in production must gate the data that shapes the model.

**Trust is one measurement discipline applied to both sides of the model** — the confidence score that gates actions, and the gates that decide whether synthetic data is good enough to train on. It is the confidence core of the Harness (01), and the reason 02 touches both deployment (04 evidence, 05 scenarios) and training (09-gated data).

## Why it matters

Every reliability layer — gates, HITL escalation, guardrails, evals — is only as good as its confidence signal. And the industry default is broken at both ends:

- **On the action side**, the default asks the model to grade its own homework (logprobs, self-consistency, "how confident are you?").
- **On the data side**, the default generates gigabytes of synthetic data, dedupes half-heartedly, and ships it to fine-tuning — trusting a pipeline, not a measurement, and baking the generator's confident blind spots into the model.

Both are the same disease: **trusting the source of the signal instead of checking it against something outside its control.** This is the deepest and most transferable problem on the agenda.

## Core concept

### The verifiability hierarchy (what actually holds up as evidence)

1. **Tool-call returns** — the function ran; the result is a fact about the world, not a sample from the model.
2. **Retrieval support / contradiction / silence** — the retrieved context either backs a claim, contradicts it, or is silent (three-state — never cosine-similarity-as-truth).
3. **Schema/type satisfaction** — the output either satisfies the contract or it doesn't (structured outputs as the trust boundary).
4. **Outcome prediction** — a model trained on past (features → confirmed outcome) pairs. The only signal that learns *which kinds of decisions this system gets right*.
5. ✗ **Excluded** — token logprobs, self-consistency, LLM-as-judge self-eval. Evidence from inside the model's own weights.

The central claim: **confidence built from signals 1–4 strictly dominates confidence built from 5**, on calibration (Brier/ECE) and on ranking utility (which actions to escalate first) — and the gap widens under distribution shift, exactly when it matters.

### Gated data as the training-side twin of gated actions

| Gate | Question (data side) | Question (action side) |
|---|---|---|
| **Verifiability** | Is the claim checkable and true? | Is the action checkable and correct? |
| **Label quality** | Is the output the right answer? | Is the confidence score honest? |
| **Contamination** | Is the sample leaked from eval? | Is this a seen-similar action? |
| **Diversity** | Is the set coverage thin? | Is this a novel decision class? |
| **Production-gate echo** | Does the fine-tuned model pass the gated eval? | Did the gated action clear the bar? |

Same axes, same structure — measured with the same ConfBench-style discipline.

## Ecosystem role

- **Consumes from 01:** the `decision log` (feature + confidence + verdict + outcome) — the raw material for the outcome-prediction scorer and the recalibration loop, and for a labeled dataset that only exists because a harness ran in production.
- **Consumes from 04:** retrieval support/contradiction verdicts — the cheapest outside-the-model evidence that exists at scale.
- **Consumes from 05:** synthetic worlds — the source corpus for gated data generation.
- **Feeds to 01:** the confidence layer behind every gate verdict, plus the recalibrated scorer injected as a drop-in `confidence_score` provider.
- **Feeds to 03:** the confidence signal as the cost-routing input (cheap model on high-confidence-easy, expensive on the rest).

## What gets built

1. **ConfBench** — an open benchmark for confidence *scorers* (not models). Tasks with known ground truth AND verifiable intermediate artifacts (tool outputs, retrievable docs, schemas). Metrics:
   - Calibration: Brier, reliability diagrams, ECE at the *score* level (not the accuracy level).
   - Ranking utility: NDCG-style "which k decisions would you escalate first."
   - Robustness: score degradation under distribution shift.
2. **Signal extractors** — framework-agnostic extractors for tool-call verification, retrieval support/contradiction classification, schema-satisfaction checks.
3. **The Trust scorer** — a small calibrated model (gradient-boosted or logistic on features from 1–4) that is honest about its uncertainty — the thing LLMs can't do by construction.
4. **Gated data pipeline** — the one existing in 09: contamination checks (membership, n-gram, semantic-duplication), diversity steering (embedding coverage), verifiability gates, provenance tracking. Rebuilt here as a library so any fine-tuning project can use it.
5. **Recalibration loop** — fetches from the decision log, reconciles against confirmed outcomes (delayed, partial), retrains the scorer on a schedule, reports the escalation band tightening.

## Architecture sketch

```
proposed action
   ├─ tool-call verifier   → {ran, result_sign, error}
   ├─ retrieval contrad.   → {support, contradict, silent}
   ├─ schema checker       → {satisfied, violation_kind}
   ├─ outcome predictor    → P(good | features, past log)
   └─ (never) logprobs / self-consistency
              ▼
     feature vector → calibrated scorer → confidence [0,1]
              ▼
         Harness gate (01) → event log → recalibrate
```

```
generator seeds (05 worlds, real docs, logs)
   ├─ verifiability gate   → per-sample check
   ├─ label-quality gate   → review/escalate
   ├─ contamination gate   → reject/quarantine
   ├─ diversity steering   → target under-covered regions
   └─ provenance per sample
              ▼
     training set → fine-tune → gated eval (echo) → PASS
```

## Research program

- **R1: The dominance claim.** Formal comparison of evidence-based vs self-reported confidence across ConfBench tasks, controlling for task difficulty and distribution shift. Prediction: at equal calibration, evidence-based scores retain ranking utility under shift; self-report collapses.
- **R2: The verifiability gap.** Characterize which actions are unverifiable (no tool, no retrieval, no schema). For those, the gate must escalate by default — quantify the fraction of realistic workloads where this is the binding constraint.
- **R3: Outcome prediction features.** Which (features → outcome) models and feature sets work on real decision logs? Minimal labeled dataset size for the outcome predictor to beat calibrated self-report?
- **R4: Confidently-wrong inheritance.** Does a weak model fine-tuned on strong-model synthetic data inherit the strong model's confident blind spots? Detect and measure via a verifiability sample that includes traps the generator would get wrong.
- **R5: Gated-data economics.** When contamination and diversity gates quarantine N% of generated data, what is the cost and value — does the fine-tune measurably beat an ungated pipeline at the same budget?

## Risks / failure modes

- **Verification trap.** Over-reliance on verifiable signals biases the gate toward *checkable* over *correct* actions. Is this real, and is it acceptable? Measure it against 01's gated-decision benchmark.
- **The adversarial-eval spiral.** Evals labeled by LLMs drift. Keep real documents and real confirmations in the loops.
- **Contamination of the evals themselves.** The eval set is in the internet; the data generator saw it. Build ConfBench with a holdout discipline that never leaks into generation.
- **The loop doesn't close.** If confirmations never arrive, the log is a dashboard. Design outcome-collection into the harness side.

## Success signals

- ConfBench is used outside this repo (a submission or an external contributor).
- A published-measured claim: evidence-based scoring dominates self-report *under distribution*, numbers on the table.
- The Trust scorer runs inside 01, and the escalation band measurably tightens over a real decision log.
- A fine-tune on gated data measurably beats the ungated baseline at the same budget — with the quarantined slice's negative effect shown.