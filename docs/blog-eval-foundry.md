# Building a benchmark like ARC does, then measuring whether it actually works

Field notes from implementing the Calibrated Evaluation Foundry, a benchmark-construction pipeline inspired by ARC-AGI-3, JudgeBench, and Airbnb's eval engineering — then stress-testing its own parameters against real human-calibration substitutes, a real contamination surrogate, and a real frontier model.

## The problem with benchmarks

ARC-AGI-1 survived five years of scaling. ARC-AGI-2 lasted months. ARC-AGI-3's technical report documents why: benchmarks get eaten by a "generate → verify → train in a loop" attack once models can sample the task space densely enough. Their own Gemini-3 verification model, never told ARC's integer-to-color mapping, used the correct mapping in its reasoning chain. The data was in the model. Benchmarks don't die of saturation, they die of being absorbed.

ARC's answer was a production methodology: human-calibrated tasks (every environment attempted by 10 humans, solved by at least 2), random-policy floors (1 in 10,000), efficiency scoring against human baselines, and private splits structurally out-of-distribution from public ones. Humans score 100%. Frontier models score under 1%.

It's a recipe, so I built it as a pipeline. Then I measured the recipe's own parameters to see which ones actually matter. Benchmark builders almost never do that part.

## The pipeline

The Calibrated Evaluation Foundry generates verifiable agent tasks (programmatic verifiers only, no judge scores an answer), runs them through a gauntlet (random-policy floor, fuzz, reproducibility, novelty), calibrates difficulty against a human oracle with ARC's 2-of-10 bar, fits a difficulty model, stratifies public/private splits matched on difficulty, scores solvers with ARC's RHAE efficiency metric, and monitors contamination with reasoning-chain leak probes.

The whole thing is deterministic and offline. Every parameter was inherited from somewhere: ARC's 1/10,000, Airbnb's kappa≥0.85, the 5x action budget. Inherited parameters are opinions until measured.

## What Airbnb's articles don't test

Airbnb's two 2026 posts are the direct ancestors of this project: "eval-driven development" gives the layered-evaluation discipline (programmatic checks → LLM-as-judge → human) and the judge-calibration loop (golden dataset, kappa/alpha agreement, refine, re-run); "from weeks to a day" gives the deterministic-caching foundation and the epistemic/aleatoric noise split. Both are excellent engineering discipline. Neither is *measured* engineering discipline — they're prescriptive. "Target kappa in the high-80s to 90s." "3-5 well-calibrated evaluators, not 20-30 noisy ones." Nowhere do either article show what happens when you violate those numbers, or where the boundary of "still valid" actually sits.

That's the gap this project exists to fill, and S1 (below) is the direct answer for the Foundry's own equivalent of Airbnb's judge-calibration knobs: compress the difficulty signal too far, and the difficulty model doesn't just get *worse* — it inverts and starts lying with confidence. Airbnb never shows you that cliff for kappa; ARC never publishes it for their own 2-of-10 bar. S6 (also below) extends the same discipline to Airbnb's judge-calibration loop directly: if a calibrated LLM judge pre-screens task difficulty before spending human-attempt budget, exactly how much of that budget can you cut before the difficulty model starts lying — and it turns out the real judge itself has a compression bias almost identical in shape to S1's synthetic one, discovered by running the actual pipeline rather than assuming the judge is neutral.

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

That result is entirely synthetic, though — the "leaked knowledge base" is a set-membership check, not an actual model. S4b closes that gap.

### S4b: the real-surrogate contamination probe

S4 validates the leak-probe *mechanism*. This asks whether a real model actually leaks. `run_llm_leak_probes` sends a real model (DeepSeek `deepseek-chat`) a task's structural hint — tool names and argument keys only, every value withheld — and checks whether the completion reproduces the withheld values anyway. That's the literal Gemini-3 scenario from the ARC report: a model that "knows" content it was never shown.

Across 20 never-leaked tasks against a model that has never seen this benchmark (it can't have — these tasks are generated fresh, per run, from a mock tool registry that doesn't exist anywhere on the public internet): **0 of 20 probes fired.** False-fire rate 0.0000, matching S4's synthetic clean-baseline number almost exactly. This is the correct outcome and the boring half of the test — the interesting half needs a model that actually *has* seen the benchmark, which requires either waiting for these tasks to leak somewhere or deliberately fine-tuning a small model on a subset (the natural S4c). Reporting a 0% false-fire rate on an honestly-clean real model is still worth publishing: it's the calibration baseline any future positive detection has to be read against.

### S6: how much human-attempt budget does a judge save you?

Directly extends Airbnb's judge-calibration loop into a budget question: if a calibrated LLM judge pre-screens which tasks are unambiguously easy or hard from the prompt alone (no trajectory, no oracle), how many of the 10 human attempts per task can be skipped before the difficulty model starts lying? The judge here is a real model (DeepSeek), not simulated — every threshold in the sweep reuses one real judge call per task, so widening the sweep costs nothing extra.

| screening threshold | tasks auto-resolved | human-calibrated | budget used | calibration monotonicity |
|---|---|---|---|---|
| 0.0 (no screening) | 0/60 | 60 | 100% | -0.7244 |
| 0.1 | 6/60 | 54 | 90% | -0.7129 |
| 0.2 | 11/60 | 49 | 81.7% | -0.7244 |
| 0.3 | 51/60 | 9 | 15% | -0.5538 |
| 0.4 | 51/60 | 9 | 15% | -0.5538 |
| 0.5 (max screening) | 60/60 | 0 | 0% | -0.6942 |

Two findings, not one. First, the expected result: a real judge saves real budget — thresholds 0.1-0.2 cut 10-18% of the human-attempt budget at essentially no monotonicity cost (-0.71 to -0.72, indistinguishable from the -0.72 unscreened baseline). Second, the unexpected one: **the real judge's own score distribution is compressed.** Across all 60 tasks it never once rated anything above 0.6 on a 0-1 difficulty scale — it has no confident "hard" tail, only a "trivial" one and an undifferentiated middle. That's why the jump from 20% to 15% budget is so sharp (11 → 51 auto-resolved between thresholds 0.2 and 0.3) and why monotonicity dips at 15% budget before partially recovering at 0%: the judge is applying S1's difficulty-compression failure mode to *itself*, discovered empirically rather than assumed. A benchmark builder who trusts a judge's difficulty ratings at face value, without measuring the judge's own score distribution the way S1 measures the generator's, is repeating the exact mistake S1 exists to catch — one level up the stack.

### The real-LLM run: the first honest human-vs-AI point on this benchmark

Every number above compares synthetic solvers (random, greedy, perfect) against each other or against the simulated oracle. None of it says anything about a real system. `LlmSolver` — an OpenAI-compatible bridge already in the codebase — was wired to DeepSeek's `deepseek-chat` endpoint with proper bearer-token auth (it previously had none) and run against the live benchmark at two scales:

| solver | 23-task pilot | 60-task confirmatory |
|---|---|---|
| random | 0.000 | 0.000 |
| greedy (prompt-following heuristic) | 0.304 | 0.240 |
| **DeepSeek (real model)** | **0.826** (82.6% solved) | **0.907** (90.7% solved) |
| perfect | 1.000 | 1.000 |

DeepSeek solved 90.7% of the 60-task run (75 generated, 60 survived the gauntlet + 2-of-10 calibration bar) at RHAE 0.907 — consistent with the smaller pilot and, at 2.6x the sample size, the more trustworthy of the two numbers per S2's own sample-size-scaling finding. Both runs land in the same place: well above the hand-written greedy heuristic, close to the perfect-solver ceiling. This is a genuinely new data point — no one has published a real-model RHAE score on this pipeline before this pass. A local Ollama endpoint was not available in this environment to run the same comparison against a smaller open-weight model — see honest limits below.

## The absorption thesis, stress-tested

The core claim is "benchmarks die of absorption, not saturation." The obvious counterargument: isn't absorption just saturation happening one level down — at the level of the training data instead of the model's raw capability — i.e. a relabeling of the same phenomenon, not a distinct failure mode?

S1 and S3 are the actual evidence against that collapse. If absorption were merely saturation-by-another-name, a benchmark's difficulty axis should degrade *gracefully* as absorption increases — harder tasks would just slowly get easier, same ordering, compressed range. That is not what S1 shows. Difficulty-scale compression doesn't compress the difficulty model's *accuracy*, it **inverts its sign** — a smoothly, confidently *wrong* model that still reports high internal consistency (split predictability stays 0.8-0.9 even while calibration monotonicity flips positive). A model whose validity had merely saturated would report low confidence or high variance on the thing that broke. A model that's been absorbed reports high confidence in the wrong direction. S3 sharpens this further: the difficulty model's in-sample fit (-0.59) has nothing to do with its out-of-fold generalization (-0.15) — the axis that looks measured is actually memorized structure, which is the mechanism-level description of what "absorption" means for a benchmark's own difficulty model, not just for the models being benchmarked. Saturation is a scalar going to zero. Absorption is a sign flip with preserved confidence. They are different failure signatures, and S1/S3 is what tells them apart on a benchmark you control end to end.

## SOTA evals literature: what's changed since ARC and Airbnb

Beyond ARC-AGI-1/2/3, JudgeBench, and METR (all already load-bearing above), four threads from 2025-2026 evals research bear directly on what the Foundry does and doesn't yet cover:

- **Agentic trajectory evaluation.** Recent work (a 2026 survey on LLM-based agent evaluation, and specialized tools like TrajAD for runtime trajectory-anomaly detection) has moved past "final answer correct?" toward step-level trajectory scoring — tool choice, argument correctness, decision order, and *when* an agent should have stopped but didn't. The Foundry already does the strong version of this for free: `exact_trajectory_verifier` and `reference_run_verifier` check the full call sequence, not just the outcome, and RHAE's action-count penalty directly punishes an agent that "looks busy" without being efficient. What it doesn't do yet is anomaly *localization* mid-run (TrajAD's contribution) — the Foundry's verifiers are binary pass/fail on the completed trajectory, not per-step diagnostics.
- **Reward hacking and verifier gaming under RL.** 2026 work on RLVR ("LLMs Gaming Verifiers," reward-hackability audits of code-RL training environments, adversarial hacker-fixer loops for hardening agent benchmarks) documents models that learn to exploit *what the verifier fails to enforce* — monkey-patching test harnesses, deleting assertions, exploiting credit leakage from spurious reasoning traces. This is the generate-verify-train loop from the ARC report, formalized: it's not hypothetical, it's a measured training dynamic. The Foundry's verifiers are programmatic and check exact trajectories/values, which closes the most common hacking surface (a model can't monkey-patch a Python assertion it never has access to) — but nothing in the pipeline currently tests whether a *solver* under a training loop (not just a one-shot eval) starts exploiting `exact_trajectory_verifier`'s specific matching logic instead of solving the task. That's untested, and it's the single most important gap this literature surfaces.
- **Contamination detection beyond n-gram matching.** 2026 work (DyePack's backdoor-based flagging, distributional and black-box sample-level detection methods) responds to a real weakness: n-gram and exact-match detection misses rephrased or paraphrased leaked content entirely, and gets more expensive as pretraining corpora grow. The Foundry's contamination monitor (S4/S4b) is value-level signature matching, which is closer to DyePack's spirit than plain n-gram (it matches the *structural fingerprint* of a solution, not just prose overlap) — but it has no defense against a model that reproduces the right values in a *rephrased* structure, and no backdoor-style provable-flagging mechanism. Both are natural S7/S8 candidates.
- **LLM-as-judge reliability.** "Reliability without Validity" (already cited in HANDOFF) is part of a larger 2025-2026 body confirming judges are unreliable in specific, structural ways — position bias strongly tied to the quality gap between compared outputs, no judge uniformly reliable across benchmarks, frontier judges failing over half of dedicated bias tests. S6's finding (the real judge's own difficulty ratings are compressed, never using the top of its scale) is a small, concrete instance of exactly this literature's warning, caught empirically rather than assumed from the literature — which is the point of building the pipeline instead of just citing the papers.

## What the evolution taught

1. **Inherited parameters are opinions.** ARC's 1/10,000 and Airbnb's 0.85 kappa are sane defaults, but the difficulty scale and the human skill bar measurably change whether the benchmark tells the truth. Benchmark builders should publish the sensitivity, not just the default.

2. **The difficulty model is where benchmarks lie first — including judges standing in for it.** Ours overfits structural features (S3); a real LLM judge used as a difficulty screener carries its own compression bias (S6). The calibration oracle, human or otherwise, is not a nice extra. It's the only thing that grounds the difficulty axis, and every proxy for it needs the same sensitivity analysis S1 applied to the generator.

3. **The stratification property is the canary.** Split predictability survived every parameter stress test (0.8 to 1.0). When a benchmark's public and private splits stop predicting each other, something upstream broke, and the difficulty model is the first suspect.

4. **Reproducibility is free if you design for it.** The entire pipeline, from generation to scoring, is byte-reproducible across seeds by construction. The variance you must worry about is the sampling marginal (which tasks), not the seed.

5. **You can validate a contamination monitor — and its real-model baseline is cheap to check.** Leak probes have an operating curve (S4) and a real-surrogate reading (S4b). If your contamination detection can't produce either, it's a dashboard, not a monitor.

6. **Absorption and saturation are different failure signatures, not synonyms.** Saturation is a scalar collapsing toward zero. Absorption is a sign flip with preserved (or increased) confidence — S1's difficulty model doesn't just get worse under compression, it gets *wrong and sure of itself*. That's the distinguishing evidence, not an assertion.

7. **A judge saves real budget, at a real cost you have to measure.** S6's real-DeepSeek judge cut human-calibration spend by 10-18% at essentially no monotonicity loss in its safe zone — and started lying past it, in a shape that mirrors S1. Airbnb says "measure judge agreement." This is what measuring it against your own pipeline's actual cost function looks like.

## The honest limits

The human oracle is still simulated for the main benchmark run — real-human calibration now has infra behind it (`CalibrationQueue` / `RealHumanOracle`, protocol-conformant with `SimulatedOracle`, proven by a mock-backed integration test), but zero live human data. That is the biggest remaining gap and it is deliberately not faked here: `RealHumanOracle.calibrate()` raises instead of fabricating an outcome for a task whose attempt quota isn't met.

The real-LLM run used DeepSeek only. A local Ollama endpoint (for a comparison against a smaller open-weight model) was not available in this environment — the run that would produce that comparison is queued as the natural next step, not run.

S4b's real-surrogate contamination probe reports a clean (0% false-fire) baseline on a model that has genuinely never seen this benchmark. It says nothing about detection on a model that *has* leaked — that requires either an actual leak event or a deliberate fine-tune, neither of which happened here.

Harder task domains (compositional multi-step, retrieval-grounded, classification) — the generality question, does this methodology transfer beyond tool-use — were explicitly scoped out of this pass. The task domain remains narrow by design: tool-use over a mock registry, so the methodology stays the subject, not the tasks. The benchmark itself is still not competitive with ARC's in difficulty. It's a proof that the methodology runs end-to-end with every property measured, now including three properties (real-LLM RHAE, real-surrogate contamination, real-judge budget tradeoff) that weren't measured before this pass.

---

All studies are reproducible: `uv run python -m trust.forge.studies.s1_sweeps` (and s2/s3/s4/s6), `uv run python -m trust.forge.studies.s4b_real_surrogate --tasks 20` (needs `MODEL_PROVIDER_BASE_URL`/`MODEL_PROVIDER_MODEL_ID`/`MODEL_PROVIDER_API_KEY`), artifacts in `docs/validation/studies/`. The real-LLM benchmark run: `uv run python -m trust.forge.cli bench --llm --llm-base <endpoint>/v1 --llm-model <model> --llm-name llm-<label>`.
