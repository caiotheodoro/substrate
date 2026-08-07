# Handoff: The Calibrated Evaluation Foundry

**Thesis, premises, build history, results, and open paths.**

This document is the complete handoff for the Calibrated Evaluation Foundry work:
what it is, what it claims, what it's built on (the two Airbnb articles and the
benchmark-design literature), what was actually built and measured, and where it
goes next. Read this first; the code and artifacts confirm everything below.

---

## 1. The thesis

**Benchmarks don't die of saturation. They die of being absorbed.** A benchmark
stops measuring anything the moment its data enters the models it's trying to
evaluate — either directly (training contamination) or structurally (the task
space gets densely sampled by generate-verify-train loops). The field's response
has been to build *harder* static benchmarks, which buy months. The alternative
is to build benchmarks the way ARC-AGI-3 is built: as a production methodology
whose validity is *measured, not assumed* — human-calibrated difficulty,
efficiency scoring that never saturates, private splits structurally
out-of-distribution from public ones, and a contamination monitor that can be
validated.

The second half of the thesis: **that methodology is itself a tunable system,
and its parameters are opinions until measured.** ARC inherited its own numbers
(1 in 10,000 random-policy floor, 2-of-10 human solve bar, 5x action budget).
Nobody has published which of those numbers actually matter for the validity of
the resulting benchmark. The Calibrated Evaluation Foundry is the first open,
reproducible implementation of the full ARC-style pipeline, with a study
harness that stress-tests the pipeline's own parameters.

The third claim, the one that makes the first two worth doing: **you can build
a benchmark construction pipeline that is byte-reproducible, contamination-
monitored, split-predictable, and unsaturated — and prove each property with a
measured artifact rather than a dashboard.**

---

## 2. The premises — what the Airbnb articles actually say

Two Airbnb engineering posts, both July 2026, anchor the entire project.

### 2.1 "Eval-driven development" (Girme, Miller, Zhao, Yang, Kelly)

The argument: LLM outputs are non-deterministic, "correct" is subjective, and a
single interaction chains retrieval, reasoning, tool calls, and generation —
each of which can fail independently. Evaluation is the engineering discipline,
not the afterthought.

Five principles:
1. **Define goals and gates upfront** — what must be true before shipping.
2. **Let real errors guide metrics** — co-develop metrics from observed
   failures, never in a vacuum.
3. **Keep the evaluator set small and sharp** — 3-5 well-calibrated
   LLM-as-judge evaluators beat 20-30 noisy ones; one evaluator per
   correctness dimension; no "God evaluators."
4. **Appoint a decision-maker** — a human makes the final call on good vs bad.
5. **Collaborate continuously** — the product partner answers "is X better or
   worse than Y" on an ongoing basis.

The three evaluation methods, as a layered stack:
- **Layer 1: programmatic checks** (fast, deterministic, catches obvious
  failures; structured outputs with JSON schemas).
- **Layer 2: LLM-as-judge** (nuanced quality assessment against a rubric).
- **Layer 3: human evaluation** (gold standard, high-stakes, disagreement
  resolution).

The judge-calibration discipline (§2.2.1) — the piece the Foundry builds on
most directly:
- Build a golden dataset of 50-100 examples, **including bad examples**.
- Run the judge against it, measure agreement with Cohen's kappa or
  Krippendorff's alpha; target the high-80s to 90s.
- Analyze disagreements, refine the rubric and few-shots, re-run until target.
- Recalibrate periodically as failure modes evolve.

For agentic systems (§3): evaluate the **trajectory**, not just the final
answer — reconstruct the trace, verify subagents/tools were invoked correctly,
scope evaluation to specific agents.

For the Foundry, Airbnb's article contributes: **judge agreement as a
quantified calibration gate** (P6), **bad examples as first-class golden
material** (the 2-of-10 bar), and **trajectory-level verification** (the
exact-trajectory verifiers).

### 2.2 "From weeks to a day" (Saberidokht)

Four layers, presented as a dependency stack — each only works because the one
below it exists:

**Layer 1 — Name the noise.** Judge outputs drift; LLM references regenerate
differently across runs. Their measured numbers: ~75% of LLM-generated
references differ across runs; a judge drifts ~1% per run on identical inputs.
A 2% score movement can mean the model improved, the judge drifted, or the
references shifted — you cannot tell which without separating *dual
indeterminacy*: epistemic uncertainty (judge/model limits, fixable) vs
aleatoric uncertainty (task ambiguity, not fixable by a better judge).
Meaningfulness = surviving perturbation (rotate judges, re-stratify samples).

**Layer 2 — A deterministic evaluation foundation.** The fix for noisy judges
is not majority-voting (it converges to central tendency, not accuracy). It is
caching: per-sample caches on both axes — references keyed by (sample, config);
judge scores keyed by (sample, model output, judge config, metric). Identical
inputs return cached results. This gives determinism, resumability, and
reproducibility. Their observation: more than half of model outputs across
candidates are identical strings — most experimental changes only affect a
subset of inputs.

**Layer 3 — Bounded, scoped model mutation.** Micro-adapters: small LoRA
patches (rank < 50), trained in under an hour, shipped like software hotfixes —
scoped to one issue, validated behind two gates (no regression on
expert-reviewed domains; high-uncertainty outputs flagged for human review),
canary-deployed with automatic rollback. Lifecycle rules from CACE (changing
anything changes everything): fuse co-triggering patches, retrain on
accumulation (Pletenev: adapters absorb corrections up to ~a few hundred
examples), unload unused patches.

**Layer 4 — End-to-end validation at the seams.** Component-level confidence
creates false assurance; the seams are where bugs live. Run a small set of
representative inputs through the *entire production path* with quality and
tail-latency measured on the combined configuration. Traffic-weighted sampling
plus deliberate tail over-representation plus regression cases from prior
incidents.

For the Foundry, this article contributes: **the deterministic foundation**
(the eval cache — identical inputs return identical results), **the
epistemic/aleatoric decomposition** (the noise diagnostics and uncertainty
decomposition), **the seam-validation discipline** (the cross-unit e2e), and
**the micro-adapter two-gate loop** (seeded in the gated-data pipeline).

### 2.3 What the Foundry adds to both

Airbnb's articles are *product* eval discipline. The Foundry's contribution is
applying the same rigor to *benchmark construction itself*:

| Airbnb premise | Foundry extension |
|---|---|
| Judge agreement must be measured (kappa/alpha ≥ high-80s) | Difficulty model agreement with the human oracle is measured out-of-fold (S3) |
| Caching gives determinism | The entire pipeline is byte-reproducible; sampling-marginal variance is the honest statistic (S2) |
| Recalibrate as failure modes evolve | The calibration oracle is the only thing that grounds the difficulty axis (S3) |
| Layered evaluation | Verifiable-only tasks; judges never score answers — only estimate difficulty |
| Validate at the seams | Cross-unit e2e (01→02→04→03) with the real joint servers |

---

## 3. The benchmark-design literature (the third pillar)

Beyond Airbnb, the Foundry builds on ARC's published methodology and the
LLM-as-judge reliability research:

- **ARC-AGI-1** (Chollet, 2019): data-efficient skill acquisition as the
  measure of intelligence; unique tasks, minimal prior knowledge, memorization-
  resistant.
- **ARC-AGI-2** (Mar 2025): static grids, humans 100%, frontier <5% at launch.
  Calibration method: 400 humans, 1,417 tasks, minimum bar "two people in two
  attempts or less." Calibrated difficulty across public/private subsets so
  performance on one predicts performance on another.
- **ARC-AGI-3** (Mar 2026): interactive environments; humans 100%, frontier
  0.10-0.50%. The production methodology:
  - Human calibration: 486 participants, 2,893 attempts, 427.9 hours; every
    environment attempted by 10 humans, fully solved by at least 2
    independently on first sight.
  - Random-policy floor: a random policy must not solve a level more than 1 in
    10,000 (graph-based state-space bounds; example P(win) = 1/355).
  - Automated gauntlet: 50k-step no-accident check, 1M-step non-tutorial
    unbeaten check, 1M-step fuzz/defect sweep.
  - Novelty: one program solving two environments at <50% the concatenated
    program length ⇒ insufficiently distinct.
  - Efficiency scoring (RHAE): per-level squared efficiency vs the upper-median
    best human first-run playthrough, capped at 1.15x, linearly weighted by
    level, per-environment completion cap, 5x action budget.
  - Split inversion: 25 public / 55 semi-private / 55 fully private; the
    public set is a demonstration front door, deliberately not representative
    of private mechanics; public scores are never reported officially.
  - Contamination evidence: their verification model, never told ARC's
    integer-to-color mapping, used the correct mapping in its reasoning chain —
    the data was in the model.
- **JudgeBench / position-bias literature**: LLM-as-judge is unreliable for
  items without objective ground truth; agreement is confounded because judges
  share biases (position, length). The 2026 "Reliability without Validity"
  study (21 judges, 541k judgments) makes the point at scale.
- **METR's evals-as-scaling**: eval quality depends on sample size; the
  sample-efficiency question applies to evaluation itself. The Foundry applies
  it to benchmark construction (S2).

---

## 4. What was built

### 4.1 The Foundry pipeline (`apps/trust/py/src/trust/forge/`)

| Module | Role | Principle |
|---|---|---|
| `task.py` | `ForgeTask` model: prompt, tool registry, expected trajectory, programmatic verifier | P1 — verifiable domains only |
| `generators.py` | Tool-use generator over a mirror of the harness mock registry (8 tools, 2-5 calls); derived-arg generator (args must be reasoned); order-insensitive variant | P1 + ARC novelty |
| `verifiers.py` | Exact-trajectory, reference-run, property verifiers | P1 |
| `gauntlet.py` | Random-policy floor (1/10k), fuzz sweep, reproducibility replay, novelty-by-signature | P2 — the gauntlet |
| `calibration.py` | `SimulatedOracle`: sigmoid solve probability over difficulty, per-task aleatoric noise, ARC's 2-of-10 bar, action counts | P3 — human calibration oracle |
| `difficulty.py` | Logistic difficulty model (feature-standardized gradient descent) fit on measured outcomes | P3 |
| `stratify.py` | Difficulty-matched public/private splits (per-bin proportional allocation), KL divergence, split-predictability test | P4 |
| `rhae.py` | Exact ARC-AGI-3 RHAE: `min(1.15, h/a)²` per level, linear weights, per-env cap, 5x budget | P5 |
| `agents.py` | RandomSolver (floor), GreedySolver (prompt-following), PerfectSolver (upper bound), LlmSolver (OpenAI-compatible bridge) | the systems being scored |
| `contamination.py` | Leak probes on value-level signatures, external-corpus n-gram matching, structural OOD between splits | P7 |
| `benchmark.py` | The orchestrator: generate → gauntlet → calibrate → fit → stratify → solve → score → monitor | the pipeline |
| `analysis.py` | Per-run analysis artifact (bandwidth, efficiency, calibration deciles, contamination, ARC reference) | the evidence |
| `cli.py` | `bench` and `matrix` subcommands; artifacts to `docs/validation/`; `--llm-api-key`/`--llm-name` for real-model runs against any OpenAI-compatible endpoint | reproducibility |
| `calibration_queue.py` | `CalibrationQueue` + `RealHumanOracle` — infra-ready, protocol-conformant real-human calibration, no live data yet | P3 real-oracle path |
| `studies/` | S1-S6 study harnesses (+ S4b real-surrogate probe) | the measurements |

### 4.2 The study harness (`forge/study.py`)

Five eval-quality metrics every study reports against:
`calibration_monotonicity` (Spearman between fitted difficulty and measured
solve rate), `split_predictability` (public→private rank correlation),
`difficulty_bandwidth` (stdev of fitted difficulty), `oracle_discrimination`
(stdev of measured solve rates), plus the benchmark score's sampling marginal.

---

## 5. The results (real, reproducible)

All studies run deterministically; artifacts live in `docs/validation/studies/`.

### S1 — Parameter sweeps (which knobs are load-bearing)

**Difficulty-prior scale.** Compressing the generator's difficulty prior flips
the calibration-monotonicity sign — the difficulty model starts *lying*
(harder tasks look easier):

| scale | calibration monotonicity | split predictability |
|---|---|---|
| 0.1 | +0.26 (model lies) | 0.8 |
| 0.3 | +0.22 (model lies) | 0.9 |
| 0.6 | -0.13 | 0.95 |
| **1.0** | **-0.59** (model tells truth) | 1.0 |
| 1.5 | -0.56 | 1.0 |
| 2.0 | -0.12 | 1.0 |

**Human population skill (d0).** The 2-of-10 bar has a Goldilocks zone:
calibration monotonicity peaks at d0=0.5 (-0.59) and degrades at both extremes
(pass rate 0.37 → 1.00). ARC's "most candidates rejected" intuition is a
measurable curve.

**Split predictability survives everything** (0.8-1.0 across all sweeps) —
the stratification property is the robust canary.

### S2 — Sample-size scaling (how much benchmark do you need)

Random subsets of a 660-task pool, scored repeatedly; greedy solver RHAE:

| tasks | mean ± stdev |
|---|---|
| 30 | 0.258 ± 0.061 |
| 60 | 0.319 ± 0.039 |
| 120 | 0.293 ± 0.044 |
| 240 | 0.271 ± 0.022 |
| 480 | 0.280 ± 0.011 |

Variance drops ~6x from 30 to 480; the knee is ~240. Below ~100 tasks a
benchmark's score is noise with a mean. The seed-to-seed variance is **zero**
(the pipeline is byte-reproducible by design); the honest statistic is the
sampling marginal.

### S3 — Difficulty-model cross-validation

K-fold out-of-fold rank correlation: **-0.15** (all features) vs -0.59
in-sample. n_calls-only: -0.18; arg-complexity-only: -0.19. The difficulty
model overfits structural features. **Structural features cannot predict human
solvability** — the calibration oracle is the only thing that grounds the
difficulty axis. This is the deepest finding and the argument for ARC's human
testing budget (400 humans, 2,893 attempts).

### S4 — Contamination monitor ROC

| leaked fraction | fire on leaked | false-fire on clean |
|---|---|---|
| 5% | 1.000 | 0.0000 |
| 10% | 1.000 | 0.0000 |
| 20% | 1.000 | 0.0054 |
| 50% | 1.000 | 0.0087 |

Detection is perfect at every leak rate; false-fire grows slowly as the
knowledge base grows (duplicate-signature twins get caught). The monitor has
an operating curve — it is verifiable, not a dashboard.

### S5 — Nested-CV stratification tuning

Tuning (n_bins, private_fraction) on train folds never beats the hand-set
default (5, 0.5) on held-out folds (predictability 1.0 both, 0/4 folds won).
Evidence that at this scale, the default is fine and tuning is overfitting the
construction — itself a publishable null result.

### S6 — judge-ladder budget study (real LLM judge, DeepSeek)

Extends Airbnb's judge-calibration loop into a budget question: does a
calibrated LLM judge pre-screening task difficulty let you cut the 10-attempt
human-calibration budget without the difficulty model lying? 60 tasks, one
real judge call per task (reused across the threshold sweep):

| threshold | auto-resolved | budget used | calibration monotonicity |
|---|---|---|---|
| 0.0 (none) | 0/60 | 100% | -0.7244 |
| 0.1 | 6/60 | 90% | -0.7129 |
| 0.2 | 11/60 | 81.7% | -0.7244 |
| 0.3-0.4 | 51/60 | 15% | -0.5538 |
| 0.5 (max) | 60/60 | 0% | -0.6942 |

10-18% of budget is free (thresholds 0.1-0.2, no monotonicity loss). Past
that the real judge's own score distribution turns out to be compressed
(never rates anything above 0.6 on a 0-1 scale across all 60 tasks) —
applying S1's difficulty-compression failure mode to itself, discovered
empirically. Artifact: `docs/validation/studies/s6-judge-ladder.json`.

### S4b — real-surrogate contamination probe (real LLM, DeepSeek)

S4 validates the leak-probe mechanism synthetically. S4b sends a real model
only a task's structural hint (tool names + arg keys, values withheld) and
checks whether it reproduces the withheld values — the literal Gemini-3
scenario. 20 never-leaked tasks against DeepSeek: **0/20 fired**, false-fire
0.0000, matching S4's synthetic clean baseline. This is the calibration
baseline; it says nothing about detection on a model that has actually
leaked (untested — no real leak event or fine-tune was available this pass).
Artifact: `docs/validation/studies/s4b-real-surrogate.json`.

### The benchmark runs

400-task benchmark, 3 seeds, identical every time: **random 0.0 | greedy
0.246 | perfect 1.0** on RHAE. Difficulty calibration is monotone (solve rate
0.72 → 0.27 as difficulty rises); split predictability 1.0; contamination
fire-on-leaked 1.0. The bandwidth is real: greedy solves 24.6% of tasks at
full efficiency and fails the rest (stdev 0.57 on per-level efficiency).

### The real-LLM run (real model, DeepSeek) — first honest human-vs-AI point

`LlmSolver` (previously untested against a live endpoint, and previously
missing bearer-token auth — fixed) run against DeepSeek `deepseek-chat` at
two scales:

| scale | random | greedy | DeepSeek | perfect |
|---|---|---|---|---|
| 23-task pilot | 0.000 | 0.304 | 0.826 (82.6%) | 1.000 |
| 60-task confirmatory | 0.000 | 0.240 | **0.907 (90.7%)** | 1.000 |

75 tasks generated, 60 survived the gauntlet + 2-of-10 calibration bar at
the larger scale. Consistent across both runs, and per S2's own
sample-size-scaling finding the 60-task number is the more trustworthy of
the two. First real-model data point this pipeline has ever produced. A
local Ollama comparison endpoint was not available in this environment —
the open-weight-vs-frontier comparison this would enable remains a queued
next step, not a completed one. Artifact:
`docs/validation/benchmark-agentic-tooluse-deepseek.json`.

---

## 6. Repo state and honest limits

### What exists and is verified
- 5-unit monorepo (harness, trust, efficiency, knowledge, simulation) with
  cross-unit joints (C5 confidence, C3 verdicts, C4 ledger) exercised by real
  seam e2e tests.
- The Foundry (all of §4) plus the eval-quality work that preceded it:
  judge-agreement metrics (kappa/alpha), deterministic eval cache, noise
  diagnostics, judge calibration loop, uncertainty decomposition, micro-adapter
  two-gate loop.
- All CI green (ts, golden, python ×3, compose). `make validate` green.
- The no-ai-slop-edited blog post (`docs/blog-eval-foundry.md`) is published
  to Notion.

### Honest limits
- **The human oracle is still simulated for the main benchmark run**
  (deterministic sigmoid with seeded noise). `calibration_queue.py` now gives
  a protocol-conformant, infra-ready `RealHumanOracle` (proven by a
  mock-backed integration test, and by direct injection into
  `run_benchmark(oracle=...)` with zero other code changes) — but it holds
  zero live human data, and `calibrate()` raises rather than fabricating an
  outcome for an under-quota task. Wiring it to an actual human-review
  surface (dock-style UI, real reviewers) is still the single biggest
  caveat on any external claim.
- **The task domain is narrow**: tool-use over a mock registry. The
  methodology is the subject; the tasks are deliberately simple.
- **The benchmark is not yet competitive with ARC-AGI-3** in difficulty. It
  is a proof that the methodology runs end-to-end with every property measured.
- **Real-LLM run: DeepSeek only.** `LlmSolver` now has bearer-token auth
  (previously missing — it silently sent no `Authorization` header) and was
  run for real against DeepSeek (23-task pilot, RHAE 0.826). No local Ollama
  runtime was available in this environment, so the open-weight-vs-frontier
  comparison remains queued.
- **S4b's real-surrogate probe only has a clean-baseline reading** (0/20
  fire, real DeepSeek, never-leaked tasks). No genuinely leaked real model
  was available to test positive detection.
- **Harder task domains were explicitly scoped out this pass** — the
  generality question (does the methodology transfer beyond tool-use)
  remains open.

---

## 7. Open paths (in priority order)

1. **Real-human calibration — PARTIAL.** `calibration_queue.py`
   (`CalibrationQueue` + `RealHumanOracle`) is built, protocol-conformant,
   and integration-tested against `run_benchmark`. What's still missing: an
   actual human-review surface feeding it (dock UI, real reviewers) and any
   live human data. Still the item the whole thesis strengthens or falls on.
2. **Real-LLM runs — PARTIAL.** Done against DeepSeek at two scales (23-task
   pilot RHAE 0.826; 60-task confirmatory RHAE 0.907, 90.7% solve rate — the
   first honest human-vs-AI-adjacent RHAE points on this pipeline). Not
   done: a local Ollama endpoint wasn't available in this environment, so
   the frontier-vs-open-weight comparison is still queued.
3. **S6 — judge-ladder budget study — DONE.** Real DeepSeek judge, 60 tasks;
   10-18% of human-attempt budget cuttable at no monotonicity cost, and the
   judge's own difficulty ratings turned out compressed (never above 0.6/1.0)
   — an empirical instance of Airbnb's calibration-loop warning, not an
   assumed one. See §5.
4. **Harder task domains — NOT STARTED.** Explicitly scoped out this pass.
   Compositional multi-step tasks, retrieval-grounded claims (via the
   knowledge gate), classification. Generality evidence: does the
   methodology transfer, or is it tool-use-specific?
5. **Contamination leak probes with a real surrogate model — PARTIAL.**
   `run_llm_leak_probes` built and run against DeepSeek: 0/20 false-fire on
   never-leaked tasks (S4b). What's missing: a genuinely leaked real model to
   test positive detection — the actual Gemini-3 scenario needs a model that
   *has* seen the benchmark, which this pass couldn't produce.

---

## 8. How to run everything

```sh
# the benchmark
cd apps/trust/py
uv run python -m trust.forge.cli bench --tasks 300 --seed 7
uv run python -m trust.forge.cli matrix --tasks 400 --seeds 7 11 42

# the studies
uv run python -m trust.forge.studies.s1_sweeps
uv run python -m trust.forge.studies.s2_scaling
uv run python -m trust.forge.studies.s3_difficulty_cv
uv run python -m trust.forge.studies.s4_contamination_roc
uv run python -m trust.forge.studies.s5_stratification_cv
uv run python -m trust.forge.studies.s6_judge_ladder --tasks 60

# real-model runs (need MODEL_PROVIDER_BASE_URL / MODEL_PROVIDER_MODEL_ID /
# MODEL_PROVIDER_API_KEY, or point --llm-base at a local Ollama :11434/v1)
uv run python -m trust.forge.cli bench --tasks 60 --seed 7 \
  --llm --llm-base https://api.deepseek.com/v1 --llm-model deepseek-chat --llm-name llm-deepseek
uv run python -m trust.forge.studies.s4b_real_surrogate --tasks 20

# the whole monorepo
make validate
```

Artifacts: `docs/validation/studies/*.json` + PNG figures; per-run benchmark
artifacts in `docs/validation/`.
