# 09 · SynthGate — Eval-Gated Synthetic Data for Fine-Tuning

## Thesis

Synthetic data for fine-tuning is not a new mechanism — what changed is scale and accessibility. But the pattern in the market is a **data factory running blind**: generate gigabytes, dedupe half-heartedly, hope evaluation passes. The failure mode is specific and nasty — synthetic data bakes the generator's blind spots into the fine-tuned model, and the model gets *confidently wrong the same way the generator was wrong*.

**SynthGate treats synthetic data as a pipeline with gates.** Contamination detection, diversity scoring, and eval gates sit between generation and training, and the final gate is identical in spirit to the production gate (01): a decision per sample — keep / escalate to human review / reject.

## Why it matters

- Fine-tuning is the most direct way to specialize a model — LoRA/QLoRA/PEFT are now team-level skills, not research labs. But the quality of the data, not the technique, decides the result. Teams who fine-tune on synthetic data without checks produce models that **become confidently wrong in a way the source model was wrong** — and the regression is invisible until production.
- The 2026 market ships synthetic-data "one-button" pipelines, which is exactly the tox-building problem. The reliable pattern is scarce, gated, provenance-tracked data.
- It's a data-ops problem with a reliability heart — squarely in the agenda of trusted agents, and upstream of everything else (01, 02 — a fine-tuned model with poisoned data ruins the calibration story).

## Core concept

### The mechanism underlying synthetic data

The famous insight script: synthetic-data frees workflow is that the mechanism is old (self-distillation, "student-teacher"), the change is scale and accessibility. Teachers generate, students learn; the risk is the student inherits the teacher's *confidence in its blind spots* — it remembered the teacher's mistakes as facts.

Two defensible modes:

1. **Weak → strong (distillation)**: use a weak/cheap model to generate *labels* for tasks we verify (augmentation, style transfer).
2. **Strong → weak (distillation)**: use a frontier model to generate instruction data for a small model — *only what the small model verifiably learns without the large model's hallucination*.

Both need gates; mode 2 is the one that injects the *frontier's confidence in its own wrongness* straight into the small model unless the gates cut it out.

### The gates

| Gate | Question | Method |
|---|---|---|
| **Contamination** | Is this sample leaked from the target's training/eval set? | Membership lookups, n-gram overlap, semantic duplication detect |
| **Diversity** | Is the set coverage thin (cluster collapse)? | Embedding clustering; per-label, per-pattern categorical coverage |
| **Verifiability** | Is a claim checkable against data and does it *hold*? | Tool-backed fact check, schema validation, contradictory triplets, hand-verification subset |
| **Label quality** | Is the output the "correct answer" for the task? | Confidence-based, check-via-round-trip, human-touch |
| **Production-gate echo** | On the fine-tuned model, does a gated eval still pass? | The 01 gate built on the fine-tuned model — this is the acceptance criterion |

## What gets built

1. **Generator harness** — the synthetic pipeline (modes 1/2), with seed (log, source, transcripts) input, not just "sampled synthetic".
2. **Contamination module** — overlap detection against validation/eval reference, threshold as a reject-line; documented evasion zone (paraphrase) and its coverage.
3. **Diversity module** — cluster-based coverage maps; a generation planner that targets under-covered regions of the data-space (the *selective* generation — diversity is a steering knob, not a post-process metric).
4. **Verifiability & label gates** — check tooling (schema, fact, round trip), the per-sample verdict.
5. **Eval harness for the fine-tuned output** — the acceptance gate: before/after the fine-tune on the target eval-suite; gate on *difference*, so a fine-tune that regresses on the verified eval fails the gate.

## Architecture sketch

```
seeds (logs, source, transcripts) -- generator (modes)
       │
       ▼
   candidate pool
       │
       ├─ contamination gate  → reject / quarantine
       ├─ diversity gate      → steering: target coverage
       ├─ verifiability gate  → per-sample check
       ├─ label quality gate  → review/escalate
       ▼
   training set (provenance-tracked each sample)
       │
       ▼
       fine-tune (LoRA/QLoRA)
       │
       ▼
   production-gate eval → PASS → elsewhere (gated by 01)
                  └  FAIL → root cause tracer
```

## Research program

- **R1: The failure-modes catalog.** What are the *verified* categories of synthetic-data failure (bottleneck-alignment seasoning? skewed task distribution? label error cascades? shortcut amplification)? Define each precisely with a detector.
- **R2: Confidently-wrong inheritance.** Does a weak model fine-tuned on strong-model synthetic data *inherit the strong model's confident blind spots*? Can we detect this and catch it at the verifiability gate?
- **R3: Steering diversity.** When the diversity gate drives "target an uncovered region", does quality degrade? What's the *marginal sample-utility* of the budget? Balanced coverage vs harm.
- **R4: The contamination of the evals.** When the data-generator benchmark itself is contaminated — the eval-set is part of the internet and leaks into the teacher's own table — how do we decontaminate *our own eval*? Build it with 02's ConfBench-construction discipline in mind.

## Prior work

- Blog: *On Synthetic Data* (mechanism, where it works, where it breaks, defensible production pattern), *RAG vs. Fine-Tune* (the data-sufficiency decision), *Fine-Tuning: When It Actually Makes Sense*, *Structured Outputs* (schema as label-verification).
- Avenza/Adopt: eval gates, verification loops, structured outputs; also 01 gate and 02 verification methodology.

## Risks / failure modes

- **Configured blind.** "The generator didn't fit the model" is detected too late (after the fine-tune). That's *why* the gates run before training, and why the final gate is a *fail-fast* auto-check on evaluation.
- **The tool is not the truth.** There's no free lunch; no gates turn synthetic data into ground truth. The discipline is *validation plus checks*, and the checks are the product. The moment the pipeline is treated as a magic wand, it bakes the generator's blind spots into the model.
- **Retraining the overfit** to **the test's distribution.** The acceptance gate itself needs a solid decontamination strategy — see R4.

## Success signals

- The fine-tuned model on the eval-gated set is *measurably* above the baseline on the target eval-suite, with the regression-catches documented (the gate caught a regression *that would have shipped*).
- A published reproduction of the "confidently-wrong inheritance" claim (R2) with a detector that catches it.
- The pipeline's data conclusions for a real product had a *nontrivial slice* of the set quarantined by the contamination gate, and the fine-tune was run *without* that slice.