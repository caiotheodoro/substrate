# Building a benchmark like ARC does, then measuring whether it actually works

Field notes from implementing the Calibrated Evaluation Foundry, a benchmark-construction pipeline inspired by ARC-AGI-3, JudgeBench, and Airbnb's eval engineering, and then stress-testing its own parameters.

## The problem with benchmarks

ARC-AGI-1 survived five years of scaling. ARC-AGI-2 lasted months. ARC-AGI-3's technical report documents why: benchmarks get eaten by a "generate → verify → train in a loop" attack once models can sample the task space densely enough. Their own Gemini-3 verification model, never told ARC's integer-to-color mapping, used the correct mapping in its reasoning chain. The data was in the model. Benchmarks don't die of saturation, they die of being absorbed.

ARC's answer was a production methodology: human-calibrated tasks (every environment attempted by 10 humans, solved by at least 2), random-policy floors (1 in 10,000), efficiency scoring against human baselines, and private splits structurally out-of-distribution from public ones. Humans score 100%. Frontier models score under 1%.

It's a recipe, so I built it as a pipeline. Then I measured the recipe's own parameters to see which ones actually matter. Benchmark builders almost never do that part.

## The pipeline

The Calibrated Evaluation Foundry generates verifiable agent tasks (programmatic verifiers only, no judge scores an answer), runs them through a gauntlet (random-policy floor, fuzz, reproducibility, novelty), calibrates difficulty against a human oracle with ARC's 2-of-10 bar, fits a difficulty model, stratifies public/private splits matched on difficulty, scores solvers with ARC's RHAE efficiency metric, and monitors contamination with reasoning-chain leak probes.

The whole thing is deterministic and offline. Every parameter was inherited from somewhere: ARC's 1/10,000, Airbnb's kappa≥0.85, the 5x action budget. Inherited parameters are opinions until measured.

## What the studies found

### S1: difficulty compression flips the model from lying to telling the truth

The generator emits a difficulty prior per task (trajectory length times arg richness). I compressed and stretched it by a scale factor:

| scale | calibration monotonicity | split predictability |
|---|---|---|
| 0.1 | **+0.26** (model lies) | 0.8 |
| 0.3 | +0.22 (model lies) | 0.9 |
| 0.6 | -0.13 | 0.95 |
| **1.0** | **-0.59** (model tells truth) | 1.0 |
| 1.5 | -0.56 | 1.0 |
| 2.0 | -0.12 | 1.0 |

When difficulty is compressed, the fitted model's difficulty ranking correlates *positively* with measured solve rates. Harder tasks look easier. The parameter is load-bearing, and it fails detectably: a benchmark whose difficulty model lies produces splits that lie. The stratification property (public predicts private) is the only thing that survives.

### S1: the human calibration bar has a Goldilocks zone

Varying the human population's skill (the oracle's d0):

| d0 | pass rate (2-of-10) | calibration monotonicity |
|---|---|---|
| 0.2 | 0.37 | -0.34 |
| 0.35 | 0.66 | **-0.55** |
| 0.5 | 0.92 | **-0.59** |
| 0.65 | 0.99 | -0.47 |
| 0.8 | 1.00 | -0.32 |

If everyone passes (d0=0.8) or most fail (d0=0.2), the calibration signal degrades. There's a real operating window. ARC's "most candidates rejected" intuition turns out to be a measurable curve.

### S2: how many tasks until the benchmark stops wobbling?

Sample-size scaling, done as the honest sampling-marginal: draw random subsets of a 660-task pool, score, repeat. Greedy solver's score variance vs subset size:

| tasks | greedy RHAE (mean ± stdev) |
|---|---|
| 30 | 0.258 ± **0.061** |
| 60 | 0.319 ± 0.039 |
| 120 | 0.293 ± 0.044 |
| 240 | 0.271 ± 0.022 |
| 480 | 0.280 ± **0.011** |

Variance drops roughly 6x from 30 to 480 tasks; the knee is around 240. Below ~100 tasks, a benchmark's score is noise with a mean. This is METR's evals-as-scaling applied to benchmark construction. A benchmark isn't trustworthy until you've measured how much benchmark you need.

### S3: structural features can't predict human solvability

K-fold cross-validation of the difficulty model (fit on train folds, measure rank correlation between fitted difficulty and measured solve rate on held-out folds):

- all features (calls + tools + arg complexity): **-0.15** out-of-fold
- n_calls only: -0.18
- arg complexity only: -0.19

In-sample the model hits -0.59; out-of-fold it collapses to -0.15. The difficulty model overfits structural features. You cannot predict which tasks humans will find hard from surface features. You need the calibration oracle. ARC runs 400 humans through 2,893 attempts for a reason. Any benchmark builder who skips the human step and "estimates difficulty" is building a benchmark whose difficulty axis is fiction.

### S4: a contamination monitor you can actually validate

The leak probe fires when a task's value-level signature appears in the leaked knowledge base. Measured across leak rates:

| leaked fraction | fire on leaked | false-fire on clean |
|---|---|---|
| 5% | 1.000 | 0.0000 |
| 10% | 1.000 | 0.0000 |
| 20% | 1.000 | 0.0054 |
| 50% | 1.000 | 0.0087 |

Detection is perfect. False-fire grows slowly because duplicate signatures in the population get caught when their twin leaks. The monitor works, and it's verifiable. A contamination "dashboard" with no operating curve is not a monitor.

## What the evolution taught

1. **Inherited parameters are opinions.** ARC's 1/10,000 and Airbnb's 0.85 kappa are sane defaults, but the difficulty scale and the human skill bar measurably change whether the benchmark tells the truth. Benchmark builders should publish the sensitivity, not just the default.

2. **The difficulty model is where benchmarks lie first.** Ours overfits structural features. The calibration oracle is not a nice extra. It's the only thing that grounds the difficulty axis.

3. **The stratification property is the canary.** Split predictability survived every parameter stress test (0.8 to 1.0). When a benchmark's public and private splits stop predicting each other, something upstream broke, and the difficulty model is the first suspect.

4. **Reproducibility is free if you design for it.** The entire pipeline, from generation to scoring, is byte-reproducible across seeds by construction. The variance you must worry about is the sampling marginal (which tasks), not the seed.

5. **You can validate a contamination monitor.** Leak probes have an operating curve. If your contamination detection can't produce one, it's a dashboard, not a monitor.

## The honest limits

The human oracle is simulated (deterministic, noisy). The real-human calibration queue is the documented next step. The task domain is tool-use over a mock registry, deliberately simple so the methodology is the subject, not the tasks. The benchmark itself is not yet competitive with ARC's. It's a proof that the methodology runs end-to-end with every property measured.

---

All studies are reproducible: `uv run python -m trust.forge.studies.s1_sweeps` (and s2/s3/s4), artifacts in `docs/validation/studies/`.
