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

**An adversarial audit (post-initial-build) found real bugs in the measurement
code itself** — not style issues, defects that inverted or overstated two of
this section's own headline findings (S1's sign flip, S3's overfitting gap),
plus a degenerate efficiency metric, an unenforced calibration bar, a
tautological contamination check, a tie-blind correlation estimator used
everywhere, and several silent-failure paths in the real-LLM code. All are
fixed, verified with new regression tests written against the specific
failure, and every artifact below is regenerated from scratch post-fix. Where
a finding changed, both numbers are shown. Full list of defects and fixes:
git history on `apps/trust/py/src/trust/forge/` for the commit(s) following
this note.

### S1 — Parameter sweeps (which knobs are load-bearing)

**Difficulty-prior scale.** Corrected: compression **weakens** calibration
monotonicity, it does not flip its sign. The originally reported sign flip
("the model lies") was an artifact of a tie-blind Spearman implementation
combined with a generator that had structural duplicate-signature collisions,
both fixed in this pass:

| scale | calibration monotonicity (corrected) | calibration monotonicity (original) | split predictability |
|---|---|---|---|
| 0.1 | -0.128 | +0.26 (claimed sign flip) | 0.8 |
| 0.3 | -0.058 | +0.22 (claimed sign flip) | 0.9 |
| 0.6 | -0.297 | -0.13 | 0.95 |
| **1.0** | **-0.688** | -0.59 | 1.0 |
| 1.5 | -0.726 | -0.56 | 1.0 |
| 2.0 | -0.430 | -0.12 | 1.0 |

**Human population skill (d0).** Shape unchanged by the audit fixes — still a
Goldilocks zone, calibration monotonicity peaks at d0=0.5 (-0.688) and
degrades at both extremes (pass rate 0.37 → 1.00: 0.2→-0.567, 0.35→-0.675,
0.5→-0.688, 0.65→-0.575, 0.8→-0.498). ARC's "most candidates rejected"
intuition is still a measurable curve.

**Split predictability survives everything** (0.8-1.0 across all sweeps,
before and after the audit) — the stratification property is the canary that
held up under every version of this study.

### S2 — Sample-size scaling (how much benchmark do you need)

Random subsets, scored repeatedly; greedy solver RHAE:

| tasks | mean ± stdev (corrected) | mean ± stdev (original) |
|---|---|---|
| 30 | 0.316 ± 0.064 | 0.258 ± 0.061 |
| 60 | 0.360 ± 0.050 | 0.319 ± 0.039 |
| 120 | 0.328 ± 0.053 | 0.293 ± 0.044 |
| 240 | 0.304 ± 0.028 | 0.271 ± 0.022 |
| 480 | 0.316 ± 0.014 | 0.280 ± 0.011 |

Variance drops ~4.6x from 30 to 480 (previously reported as ~6x); the knee is
still ~240. Below ~100 tasks a benchmark's score is noise with a mean. The
seed-to-seed variance is **zero** (the pipeline is byte-reproducible by
design); the honest statistic is the sampling marginal.

### S3 — Difficulty-model cross-validation — REVERSED finding

K-fold out-of-fold rank correlation, corrected: **-0.662** (all features),
n_calls+n_tools -0.634, n_calls-only -0.418, arg-complexity-only -0.345,
n_tools-only -0.323. In-sample on the same 230-task pool: **-0.685**. That's
a 0.02 gap — not the 0.44 gap ("-0.59 in-sample vs -0.15 out-of-fold")
originally reported, which also compared two different task pools
(apples-to-oranges) rather than the same one in-sample vs out-of-fold.

**The original claim — "structural features cannot predict human
solvability, the calibration oracle is the only thing that grounds the
difficulty axis" — does not hold on the corrected data.** Two bugs drove it:
a tie-blind Spearman correlation (biasing every number here), and a generator
defect where `n_calls` and `n_tools` were mathematically identical for every
task (no tool ever repeated within a task's call sequence), so the
single-feature ablation was silently testing one feature under two names.
Fixed, `n_calls_only` and `n_tools_only` are now genuinely different numbers.
The corrected finding: on this task domain, simple structural features
predict human solve rate well and generalize out of fold almost perfectly.
Whether that holds on a harder, less structurally-legible domain is open —
ARC's 400-human, 2,893-attempt calibration budget is still the right design
choice for a domain where the difficulty surface isn't this legible, but
"the calibration oracle is the *only* thing that grounds the difficulty
axis" was too strong a claim from this data.

### S4 — Contamination monitor ROC

The leak probe's knowledge base is now built from a genuinely **independent**
reference corpus (a prior version built it from the same population being
tested — a tautology, since a leaked task trivially matches a KB derived from
itself):

| leaked fraction | fire on leaked | false-fire on clean (corrected) | false-fire on clean (original) |
|---|---|---|---|
| 5% | 1.000 | 0.0000 | 0.0000 |
| 10% | 1.000 | 0.0000 | 0.0000 |
| 20% | 1.000 | 0.0000 | 0.0054 |
| 30% | 1.000 | 0.0000 | (not run) |
| 50% | 1.000 | 0.0000 | 0.0087 |

Detection is perfect at every leak rate with zero false-fires now — cleaner
than before, because the previously-nonzero false-fire rate was itself an
artifact of the generator's duplicate-signature bug, not a real property of
the detector.

### S5 — Nested-CV stratification tuning

Now genuinely tests what it claims to: a prior version swept `n_bins` but
never passed it to the actual split-construction function, only to the
acceptance test's own binning — tuning the ruler, not the thing being
measured, which is also why the pre-audit "0/4 folds won" result was not a
real measurement. Fixed. Corrected result: mean default-config
predictability 0.975, mean tuned 1.0, tuned wins 1 of 4 folds (fold 3: default
0.900 vs tuned 1.000, other three folds tied at 1.000). Tuning wins on the one
fold where the default's fixed bin count happens to fit that fold's split
badly, not systematically — still evidence that at this scale the default is
a reasonable choice and heavy tuning buys little, just not literally zero.

### S6 — judge-ladder budget study (real LLM judge, DeepSeek)

Extends Airbnb's judge-calibration loop into a budget question: does a
calibrated LLM judge pre-screening task difficulty let you cut the 10-attempt
human-calibration budget without the difficulty model lying? 60 tasks, one
real judge call per task (reused across the threshold sweep), rerun clean
(0 network failures; a first pass hit 6/60 timeouts, caught by this same
audit's failure-tracking fix, not silently absorbed into a misleadingly flat
result):

| threshold | auto-resolved | budget used | calibration monotonicity |
|---|---|---|---|
| 0.0 (none) | 0/60 | 100% | -0.789 |
| 0.1 | 8/60 | 86.7% | -0.789 |
| 0.2 | 12/60 | 80.0% | -0.789 |
| 0.3-0.4 | 46/60 | 23.3% | -0.634 |
| 0.5 (max) | 60/60 | 0% | -0.555 |

13-20% of budget is free at thresholds 0.1-0.2, with **zero** monotonicity
loss (identical to the unscreened baseline, not just close) — cleaner than
originally reported, since the correlation estimator feeding this table is no
longer tie-biased. Past that, the real judge's own score distribution is
still compressed (never rates anything above 0.6 on a 0-1 scale across all 60
tasks), a pattern similar in shape to what S1 originally (mis)measured in the
synthetic generator — worth naming honestly given S1's own version of that
pattern didn't survive the audit. Artifact:
`docs/validation/studies/s6-judge-ladder.json`.

### S4b — real-surrogate contamination probe (real LLM, DeepSeek)

S4 validates the leak-probe mechanism synthetically. S4b sends a real model
only a task's structural hint (tool names + arg keys, values withheld) and
checks whether it reproduces the withheld values — the literal Gemini-3
scenario, matched with a word-boundary check now, not a bare substring match
(a prior version would count a value of `3` as "reproduced" by any text
containing the digits `13`). 20 never-leaked tasks against DeepSeek: **0/20
fired, 0 network failures**, false-fire 0.0000, matching S4's synthetic clean
baseline. A first pass hit 6/20 timeouts (caught by the same audit fix as
S6's); rerun clean. This is the calibration baseline; it says nothing about
detection on a model that has actually leaked (untested — no real leak event
or fine-tune was available this pass). Artifact:
`docs/validation/studies/s4b-real-surrogate.json`.

### The benchmark runs

300-task request (375 generated with derived-arg tasks, 100% gauntlet pass —
up from occasional duplicate-driven failures before the generator fix),
320/375 survived the 2-of-10 calibration bar, which is now actually enforced
(a prior version computed this bar and never filtered on it — every task was
scored regardless): **random 0.0 | greedy 0.294 | perfect 1.0** on RHAE. The
3-seed, 400-task reproducibility matrix: **random 0.0 | greedy 0.282 |
perfect 1.0**, identical across all 3 seeds. Per-task efficiency now shows
real variance (perfect solver: mean 1.32, stdev 0.036, 98.75% capped, not
100% — a prior version showed exactly 100% capped, zero variance, on every
run, since the human baseline was decoupled from task length and always blew
past the cap). Contamination monitor: fire-on-leaked 1.0, false-fire 0.0,
against the now-independent knowledge base.

### The real-LLM run (real model, DeepSeek) — first honest human-vs-AI point

`LlmSolver` (previously untested against a live endpoint, missing
bearer-token auth, and unable to recover from a single hallucinated tool call
— all three fixed) run against DeepSeek `deepseek-chat`:

| solver | solve rate / RHAE (corrected) | solve rate / RHAE (original, bug-affected) |
|---|---|---|
| random | 0.000 | 0.000 |
| greedy | 0.258 | 0.240-0.304 (two runs) |
| **DeepSeek** | **0.952 (95.2%)** | 0.826-0.907 (two runs) |
| perfect | 1.000 | 1.000 |

75 tasks generated, 62 survived the gauntlet + 2-of-10 calibration bar. Split
predictability on this specific 62-task calibrated population: 0.7, below
the 0.8 acceptance bar — a real instance of S2's own small-sample-variance
lesson (62 calibrated tasks is on the low end), not a new defect. The
original two runs (23-task pilot 82.6%, 60-task "confirmatory" 90.7%) aren't
directly comparable to this one: the gauntlet, the calibration-bar
enforcement, and the RHAE computation all changed under them. This is the
first number produced by the fully-corrected pipeline. A local Ollama
comparison endpoint was not available in this environment — the
open-weight-vs-frontier comparison this would enable remains a queued next
step, not a completed one. Artifact:
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
- **An adversarial audit found real bugs in the measurement pipeline itself,
  after the numbers below had already been drafted once.** Two headline
  findings inverted or overstated: S1's claimed sign-flip on the difficulty
  prior did not replicate (compression weakens monotonicity, it never flips
  sign — the flip was a tie-blind correlation estimator), and S3's claimed
  overfitting gap ("structural features can't predict solvability") reversed
  to the opposite conclusion once the same bug and a generator collinearity
  defect were fixed. Neither survived being checked against `scipy.stats`
  and a same-pool in-sample/out-of-fold comparison. This is disclosed here
  and in the blog post rather than quietly corrected, on the view that a
  pipeline claiming to measure trustworthiness has to survive being audited
  in public. Full defect list: git history on
  `apps/trust/py/src/trust/forge/`.
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
  (previously missing), can recover from a single hallucinated tool call
  instead of aborting the episode, and was rerun post-audit against DeepSeek
  on the fully-fixed pipeline: 95.2% solve rate, RHAE 0.952, 62/75 tasks
  survived calibration. No local Ollama runtime was available in this
  environment, so the open-weight-vs-frontier comparison remains queued.
- **S4b's real-surrogate probe only has a clean-baseline reading** (0/20
  fire, real DeepSeek, never-leaked tasks, 0 network failures on the clean
  rerun). No genuinely leaked real model was available to test positive
  detection.
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
2. **Real-LLM runs — PARTIAL.** Done against DeepSeek on the fully-audited
   pipeline: 95.2% solve rate, RHAE 0.952, 62/75 tasks survived calibration
   (the first honest human-vs-AI-adjacent RHAE point produced after the
   audit fixes — the two pre-audit runs, 82.6% and 90.7%, aren't directly
   comparable, since the gauntlet, calibration-bar enforcement, and RHAE
   computation all changed under them). Not done: a local Ollama endpoint
   wasn't available in this environment, so the frontier-vs-open-weight
   comparison is still queued.
3. **S6 — judge-ladder budget study — DONE.** Real DeepSeek judge, 60 tasks;
   13-20% of human-attempt budget cuttable at *zero* monotonicity cost
   (post-audit: identical to the unscreened baseline, not just close), and
   the judge's own difficulty ratings turned out compressed (never above
   0.6/1.0) — an empirical instance of Airbnb's calibration-loop warning,
   not an assumed one, and similar in shape to a pattern S1 originally
   (mis)measured before the audit. See §5.
4. **Harder task domains — NOT STARTED.** Explicitly scoped out this pass.
   Compositional multi-step tasks, retrieval-grounded claims (via the
   knowledge gate), classification. Generality evidence: does the
   methodology transfer, or is it tool-use-specific?
5. **Contamination leak probes with a real surrogate model — PARTIAL.**
   `run_llm_leak_probes` built and run against DeepSeek, now checked with a
   word-boundary match instead of a bare substring match: 0/20 false-fire on
   never-leaked tasks (S4b), 0 network failures on the clean rerun. What's
   missing: a genuinely leaked real model to test positive detection — the
   actual Gemini-3 scenario needs a model that *has* seen the benchmark,
   which this pass couldn't produce.
6. **Audit the audit — NOT STARTED.** This pass found 15 real defects in a
   pipeline that had already been reviewed once and looked clean. No reason
   to assume this is the last pass; a second independent adversarial review
   (ideally by someone other than the original author, or at minimum a fresh
   context with no attachment to the current fixes) is the honest next step
   before leaning further on any of these numbers.

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
