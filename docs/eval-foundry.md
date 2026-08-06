# The Calibrated Evaluation Foundry

A methodology and platform for building evals that stay unsaturated,
verifiable, and predictive — the synthesis of ARC-AGI-2/3 benchmark design,
the LLM-as-judge reliability literature, and Airbnb's deterministic-eval
engineering. Implemented as `apps/trust/py/src/trust/forge/`.

## 1. The problem

Three failure modes kill evals over time, and each has a documented case:

**Saturation.** Binary pass/fail benchmarks top out as models improve.
ARC-AGI-1 resisted pretraining scaling for five years, then fell to
test-time reasoning (o1/o3, late 2024). ARC-AGI-2 (static grids, humans
100%, frontier <5% at launch) was already being eroded by mid-2025 via
"generate → verify → train in a loop" synthetic-data attacks.

**Contamination.** The Gemini 3 verification evidence (ARC-AGI-3 technical
report): a verification model never told ARC's integer-to-color mapping
used the correct mapping in its reasoning chain — ARC data was in the
underlying model. Static datasets with public training sets get absorbed;
once the private test set is identically distributed to public
demonstrations, memorization shortcuts work at scale.

**Unreliable judges.** "Reliability without Validity" (2026, 21 judges,
541k judgments): inter-judge agreement is confounded — two judges can
agree precisely because they share a bias (position, length). JudgeBench
concluded judges are only trustworthy on items with *objectively verifiable*
ground truth. And pass/fail human evaluation doesn't scale.

The frontier answer to all three at once is ARC-AGI-3 (Mar 2026): the only
unsaturated general agentic benchmark as of March 2026 — humans 100%,
frontier models 0.10–0.50%. Its design is a *production methodology*, not
magic, and that methodology is reproducible.

## 2. The synthesis

Three camps each hold half the answer:

| Camp | What they got right | What they're missing |
|---|---|---|
| ARC Prize | Hardest problem design: human calibration bar, random-policy floor, efficiency scoring, contamination resistance | Tasks are bespoke, hand-built; no generative platform |
| Judge research | Measurement discipline: verifiable-only items, bias audits, calibration to human labels | Runs on borrowed static datasets |
| Airbnb | Deterministic foundation: eval cache, judge calibration loops, epistemic/aleatoric decomposition, seam testing | Product evals, not frontier benchmarks |

The Calibrated Evaluation Foundry assembles all three: ARC's *production
methodology* run as a *generative platform* — verifiable, human-calibrated,
efficiency-scored, contamination-monitored tasks at scale, with Airbnb's
deterministic measurement underneath.

## 3. The seven principles

**P1 — Verifiable domains only.** Every task carries a programmatic
verifier (exact-match, reference-run, or grounded-gate verdict). LRM
automation provably works in verifiable domains (ARC-AGI-3 §1.3.2: "the
domain provides an exact correctness feedback measure"). Verifiers kill
most LLM-as-judge failure modes at the root: a judge is only ever
*validating the task*, never scoring the answer.

**P2 — The gauntlet before humans.** Every generated task passes, before
any calibration: random-policy floor (random/naive agents must not solve a
level more than 1 in 10,000 — ARC-AGI-3 §3.5.2), fuzz sweep (malformed
inputs, adversarial calls, no crashes), reproducibility replay (record →
replay → byte-identical), and compression-based novelty (two tasks are too
similar if one program solves both at <50% the length of the concatenated
programs — ARC-AGI-3 §3.5). Only survivors reach humans.

**P3 — Human calibration as the difficulty oracle.** Difficulty is
measured, not estimated by a judge: a calibration queue collects
solvable-or-not (ARC's bar: every environment attempted by 10 humans, fully
solved by ≥2 independently on first sight), solve time, and action counts.
v1 uses a simulated oracle with calibrated noise (CI-deterministic); real
humans via the knowledge :8202 / harness HITL queues are the documented v2.

**P4 — Calibrated split stratification.** Fit a per-task difficulty model
(solvability probability + human action baseline). Stratify public /
semi-private / private splits to share the difficulty distribution, so
performance on one split predicts performance on another. This is the
property that makes a leaderboard honest.

**P5 — Efficiency scoring with human baselines.** Score = per-level
relative efficiency against a human baseline, squared, capped:

    S = min(1.15, h / a)²          # h = human baseline actions, a = agent actions
    E = Σ w_l · S_l / Σ w_l        # level-weighted, per-environment
    T = mean over environments

(Human baseline = upper-median best first-run human playthrough; levels
weighted 1/15..5/15 so early tutorial levels matter least; agents get an
action budget of 5× the human median.) Binary pass/fail saturates;
efficiency never does.

**P6 — Judge ladder as cost-control, calibrated to human labels.** Where
full human calibration is too expensive (thousands of tasks), a judge
ladder (cheap → strong) pre-screens *difficulty*, calibrated against the
measured human labels with Cohen's kappa / Krippendorff's alpha ≥ high-80s
(the Airbnb EDD target). Judges never score answers — they estimate
solvability, a verifiable-ish target, sidestepping the confounded-agreement
trap.

**P7 — Contamination is a first-class monitored quantity.** Three layers:
reasoning-chain leak probes (can a surrogate model complete our task
formats from hints?), corpus MinHash / n-gram matching against public data
(the trust contamination gate), and *structural OOD split design* — the
private set must be out-of-distribution relative to anything publicly
demonstrated (ARC-AGI-3's inverted 25/55/55 split; "we will never report
public set scores on the official leaderboard").

## 4. Reference numbers (kept exact)

From the ARC-AGI-2 and ARC-AGI-3 technical reports:

- ARC-AGI-2: 1,417 tasks, 400 human participants, minimum bar "two people
  in two attempts or less"; humans solve ~100%, frontier ~<5% at launch.
- ARC-AGI-3 calibration: 486 unique participants, 414 candidate
  environments, 2,893 total attempts, 427.9 hours of play; median attempt
  7.4 min; sessions 90 min, soft 20-min / hard 30-min per environment;
  pay $115–$140 + $5 per solved environment.
- ARC-AGI-3 random-policy rule: a random policy must not solve a level
  more often than 1 in 10,000 (graph-based state-space bounds; example:
  P(win) for one level exactly 1 in 355).
- ARC-AGI-3 random regimes: 50k-step no-accident sanity check, 1M-step
  non-tutorial unbeaten check, 1M-step fuzz/defect sweep.
- ARC-AGI-3 novelty: one program solving two environments at <50% the
  concatenated program length ⇒ insufficiently distinct.
- ARC-AGI-3 scoring: RHAE, per-level squared efficiency capped at 1.15×,
  linear level weights, per-environment cap, 5× human action budget.
- ARC-AGI-3 splits: 25 public / 55 semi-private / 55 fully private;
  public set deliberately not representative of private mechanics.
- ARC-AGI-3 launch scores (semi-private): Opus 4.6 (Max) 0.50%, Gemini
  3.1 Pro Preview 0.40%, GPT 5.4 (High) 0.20%, Grok-4.20 0.10%.
- Judge reliability ("Reliability without Validity", 2026): 21 judges,
  9 providers, 118 runs, ~541k judgments; agreement is confounded by
  shared bias.

## 5. Repo mapping

| Foundry component | Exists | Missing |
|---|---|---|
| Verifiable task generation | 05 sim worlds, 02 ConfBench tasks | **forge** task generator + verifiers |
| The gauntlet | 01 controlled-havoc, 05 random sweeps (partial) | **forge/gauntlet** (random floor, fuzz, replay, novelty) |
| Human calibration queue | knowledge :8202, harness HITL | **forge/calibration** protocol + difficulty model |
| Split stratification | 02 holdout discipline (A-T-10) | **forge/stratify** difficulty-matched splits + predictability test |
| Efficiency scoring | 05 SimBench coverage/Brier | **forge/rhae** (Phase 3) |
| Judge calibration | B1 loop, kappa/alpha, eval cache (A1–A3) | difficulty-prediction calibration target (Phase 3) |
| Contamination | 02 contamination gate (MinHash/n-gram) | leak probes + structural OOD design (Phase 4) |

## 6. Roadmap

- **Phase 1 — Forge core** (`forge/`): task model, generators over the
  harness tool registry, programmatic verifiers, the gauntlet. Gate: ≥95%
  of generated tasks pass; every planted-bad case rejected.
- **Phase 2 — Calibration loop** (`forge/calibration.py`, `stratify.py`):
  simulated human oracle with calibrated noise, difficulty model, human
  action baselines, difficulty-matched public/private splits, and a
  split-predictability assertion. Gate: oracle recovers planted difficulty;
  stratified splits pass predictability; deliberately-bad splits fail.
- **Phase 3 — RHAE scoring + judge ladder** (roadmap): per-level squared
  efficiency scoring, human-baseline normalization, judge-ladder
  difficulty pre-screening calibrated to measured human labels.
- **Phase 4 — Contamination monitoring** (roadmap): reasoning-chain leak
  probes, corpus matching, structural OOD split design.
- **Phase 5 — Demonstration benchmark** (roadmap): a calibrated agentic
  tool-use benchmark (~200 tasks) generated end-to-end, with every
  property published as `docs/validation/` artifacts.

## 7. What success looks like

A benchmark built by the Foundry demonstrates, with measured artifacts:

1. Unsaturation: the efficiency score is far from ceiling for any current
   system, and the distribution of per-task scores has wide bandwidth.
2. Predictability: public-split performance predicts private-split
   performance (rank correlation above threshold).
3. Verifiability: every task has a passing programmatic verifier; zero
   judge-scored answers.
4. Contamination-resistance: leak probes fire on planted leaks and stay
   silent on clean tasks; the private split is structurally OOD.
5. Determinism: the entire pipeline (forge → gauntlet → calibration →
   scoring) is byte-reproducible via the eval cache and seeded noise.
