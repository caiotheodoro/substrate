# 02 · ExEval — Confidence From Evidence, Not Self-Report

## Thesis

Model token probabilities and self-consistency checks measure how sure a model is **of itself** — not whether it is right. A model that is confidently and consistently wrong passes every self-check, because agreement with your own prior sample is not evidence from outside your own weights.

**ExEval builds confidence scores from what the model does not control**: tool-call verification, retrieval support or contradiction, schema/type checks, and past labeled outcomes. It is the confidence core of GateOS (01), and a research program on what "confident and right" actually means.

## Why it matters

Every reliability layer in the agent stack — gates, HITL escalation, guardrails, evals — is only as good as its confidence signal. The industry default is broken at its root: it asks the model to grade its own homework. Until confidence comes from outside the model, no gate built on it can be trusted. This is the deepest and most transferable research problem on the agenda.

## Core concept

**The verifiability hierarchy** (what actually holds up as evidence):

1. **Tool-call returns** — the function ran; the result is a fact about the world, not a sample from the model.
2. **Retrieval support/contradiction** — the retrieved context either supports the claim, contradicts it, or is silent (three-state, not cosine-similarity-as-truth).
3. **Schema/type satisfaction** — the output either satisfies the contract or it doesn't (structured outputs as a trust boundary).
4. **Historical outcome prediction** — a model trained on past (features → confirmed outcome) pairs, the only signal that learns *which kinds of decisions this system gets right*.
5. ✗ (excluded) **Token logprobs, self-consistency, LLM-as-judge self-eval** — evidence from inside the model's own weights.

The central research claim: **a confidence score built from signals 1–4 strictly dominates any built from 5**, in the sense of calibration (Brier score) and in the sense of ranking utility (which decisions to escalate first).

## What gets built

1. **ConfBench** — an open benchmark for confidence scoring. Not a model benchmark: a *scorer* benchmark. Tasks with a known ground truth and, critically, *verifiable intermediate artifacts* (tool outputs, retrievable docs, schemas). Measures:
   - Calibration: Brier score, reliability diagrams, ECE at the score level (not accuracy level).
   - Ranking utility: NDCG-style metric on "which decisions would you escalate if you could only escalate k".
   - Robustness: confidence *degradation* under distribution shift (the moment calibration matters most).
2. **Signal extractors** — reusable, framework-agnostic extractors for tool-call verification, retrieval support/contradiction classification, schema-satisfaction checks.
3. **The ExEval scorer** — a small, calibrated model (gradient-boosted or logistic on engineered features from signals 1–4) that is *honest about its uncertainty* — the thing LLMs can't do by construction.
4. **Reference implementation in the GateOS MCP boundary** — wires the scorer into the gate as a drop-in `confidence_score` provider.

## Architecture sketch

```
proposed action
   ├─ tool-call verifier    → {ran: bool, result_sign: ±, error: ...}
   ├─ retrieval contrad.    → {support, contradict, silent} per claim
   ├─ schema checker        → {satisfied, violation_kind}
   ├─ outcome predictor     → P(outcome=good | features, past labeled log)
   └─ (never) logprobs / self-consistency
              ▼
      feature vector → calibrated scorer → confidence [0,1]
              ▼
         GateOS gate (01)
```

## Research program

- **R1: The dominance claim.** Formal comparison of evidence-based vs self-reported confidence across ConfBench tasks, controlling for task difficulty and distribution shift. Prediction: at equal calibration, evidence-based scores retain ranking utility under shift; self-report collapses.
- **R2: The verifiability gap.** Characterize *which actions are unverifiable* (no tool, no retrieval, no schema). For those, the gate must escalate by default — quantify the fraction of realistic workloads where this is the binding constraint.
- **R3: Outcome prediction features.** Which (features → outcome) models and feature sets work best on real decision logs? What's the minimal labeled dataset size for the outcome predictor to beat calibrated self-report?
- **R4: Recalibration dynamics.** How does the scorer improve as the outcome log compounds (the 01 loop)? Does the escalation band tighten measurably, and how fast per N decisions?

## Prior work it builds on

- Blog: *Evaluation Gates Are the Reliability Moat* (confidence fallacy), *Calibration* (why calibration > accuracy in production), *What Superforecasters Got Right* (Brier score as standard, the loop almost never closes), *Structured Outputs* (schema checks as trust layer).
- Adopt AI: evaluation gates, confidence scoring in HITL, structured-output validation.
- Skills: calibration, confidence scoring, evaluation gates, LangSmith/Langfuse, retrieval (support/contradiction three-state), schema-driven structured outputs.

## Open questions / risks

- **Contradiction detection is itself an LLM judgment** — moving the trust boundary up a level. Research whether retrieval-support classification can be made deterministic (lexical overlap + entailment models) and at what accuracy it stops being useful.
- **The verification trap.** Over-reliance on verifiable signals biases agents toward actions that are *checkable* over actions that are *right*. Is this a real effect, and is it acceptable?
- **Contamination.** If outcome-labeled data is used to train the very models that produce the actions, does the scorer's calibration degrade? (See 09 SynthGate contamination work.)

## Success signals

- ConfBench exists and is used outside this repo (first external contributor / paper submission).
- A published result showing evidence-based scoring dominates self-report under distribution shift, with the numbers on the table.
- The ExEval scorer running inside GateOS with the escalation band measurably tightening over a real decision log.
