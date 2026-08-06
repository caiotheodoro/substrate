# @substrate/trust

**One measurement discipline for actions and data.** Confidence from what the model does not control — and the same gates for the data that shapes it.

## What is a verifiable research platform

A model's token probabilities measure how sure it is **of itself**, not whether it is right. Trust builds confidence from outside the model's weights:

1. Tool-call returns
2. Retrieval support / contradiction / silence
3. Schema/type satisfaction
4. Outcome history (feature → confirmed outcome pairs)

…and never from logprobs, self-consistency, or self-eval.

The same axes gate synthetic data: verifiability, label quality, contamination, diversity, and a production-gate echo after fine-tuning.

## Benchmarks

- **ConfBench** — a benchmark for confidence *scorers*: calibration (Brier/ECE at the score level), ranking utility (escalate the right k first), robustness under distribution shift.
- **Gated-data comparison** — gated vs ungated synthetic pipeline at equal budget.

## Ecosystem

- Consumes the Harness's `decision log` (outcome-labeled decisions) and `knowledge`'s grounded-gate verdicts.
- Feeds the confidence layer behind every Harness gate verdict; provides the routing signal `efficiency` needs.
- Consumes synthetic worlds from `simulation` for data generation and 01's event log from `@substrate/substrate`.

## Spec

Written (`SPEC.md`).

## State

Implemented. ConfBench (score-level Brier/ECE/NDCG-escalation + banned
baselines, holdout discipline), evidence extractors (:8010–8012), scorer
train/serve (:8020, C5), gated-data pipeline (:8030–8034), recalibration
loop (:8040–8041), r1/r2 research artifacts, judge-agreement metrics,
eval cache, noise diagnostics, uncertainty decomposition, micro-adapter
two-gate seed. 177 tests.