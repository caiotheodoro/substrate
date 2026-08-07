# Building a benchmark like ARC does, then measuring whether it actually works

Field notes from implementing the Calibrated Evaluation Foundry, a benchmark-construction pipeline inspired by ARC-AGI-3, JudgeBench, and Airbnb's eval engineering, then stress-testing its own parameters against real human-calibration substitutes, a real contamination surrogate, and a real frontier model. Full code: [github.com/caiotheodoro/substrate](https://github.com/caiotheodoro/substrate).

## The problem with benchmarks

ARC-AGI-1 survived five years of scaling. ARC-AGI-2 lasted months. ARC-AGI-3's technical report documents why: benchmarks get eaten by a "generate → verify → train in a loop" attack once models can sample the task space densely enough. Their own Gemini-3 verification model, never told ARC's integer-to-color mapping, used the correct mapping in its reasoning chain. The data was in the model. Benchmarks don't die of saturation, they die of being absorbed.

ARC's answer was a production methodology: human-calibrated tasks (every environment attempted by 10 humans, solved by at least 2), random-policy floors (1 in 10,000), efficiency scoring against human baselines, and private splits structurally out-of-distribution from public ones. Humans score 100%. Frontier models score under 1%.

It's a recipe, so I built it as a pipeline. Then I measured the recipe's own parameters to see which ones actually matter. Benchmark builders almost never do that part.

## An audit found real bugs in the measurement, so the numbers below changed

Before this pass, I asked for an adversarial code and data audit of the whole pipeline: not "does it run," but "does the code actually do what the docs and the numbers claim." It found real defects, not style nits. The two that matter most:

- **The efficiency metric (RHAE) was measuring nothing.** The simulated human baseline was generated independently of how many actions a task actually needed, so every solved task hit the metric's cap identically. RHAE and raw solve rate were arithmetically the same number, dressed up as two independent confirmations.
- **The 2-of-10 human-calibration bar was computed and then never enforced.** Tasks that failed it were scored anyway.

Plus a working list of smaller ones: a gauntlet novelty check that compared every task against a permanently empty corpus (so duplicates were never caught), a contamination monitor whose "leaked knowledge base" was built from the same population it tested (a tautology: any leaked task trivially matches itself), a Spearman correlation implementation that didn't average-rank ties (biasing the one number every study reports through), and a few silent-failure paths where a dead network endpoint and a genuine negative result produced identical-looking output.

All of it is fixed now, verified with new tests written against the specific failure, not just "the suite is green." Two of the fixes changed the actual scientific findings, not just the plumbing, and I'm reporting that directly rather than quietly swapping in new numbers: **the difficulty-compression "sign flip" below no longer replicates, and the "structural features can't predict difficulty" claim was largely an artifact of the same bugs.** Both are corrected below, with the old and new numbers side by side where it matters.

## The pipeline

The Calibrated Evaluation Foundry generates verifiable agent tasks (programmatic verifiers only, no judge scores an answer), runs them through a gauntlet (random-policy floor, fuzz, reproducibility, novelty), calibrates difficulty against a human oracle with ARC's 2-of-10 bar, fits a difficulty model, stratifies public/private splits matched on difficulty, scores solvers with ARC's RHAE efficiency metric, and monitors contamination with reasoning-chain leak probes. Code: [`apps/trust/py/src/trust/forge/`](https://github.com/caiotheodoro/substrate/tree/main/apps/trust/py/src/trust/forge).

The whole thing is deterministic and offline. Every parameter was inherited from somewhere: ARC's 1/10,000, Airbnb's kappa≥0.85, the 5x action budget. Inherited parameters are opinions until measured.

## Taking Airbnb's eval discipline one step further

Airbnb's two 2026 posts are the direct ancestors of this project. "Eval-driven development" gives the layered-evaluation discipline (programmatic checks → LLM-as-judge → human) and the judge-calibration loop (golden dataset, kappa/alpha agreement, refine, re-run). "From weeks to a day" gives the deterministic-caching foundation and the epistemic/aleatoric noise split. Both are the reason this project exists in its current shape: the layered evaluation stack, the judge-calibration discipline, and the eval cache are all load-bearing here, not just inspiration.

What both articles establish as sound engineering practice (target kappa in the high-80s to 90s, 3-5 well-calibrated evaluators) reads as guidance calibrated for product evaluation, where the loop closes on human judgment quickly. Benchmark construction is a narrower, more mechanical case of the same problem: fewer free variables, a ground-truth oracle you can query repeatedly, and a payoff (S1, S6 below) for running the sensitivity analysis all the way out. That's the piece this project adds on top: what does a difficulty model actually do as you move those numbers, in a domain simple enough to instrument completely? S6 answers it for the judge-calibration loop directly: if a calibrated LLM judge pre-screens task difficulty before spending human-attempt budget, how much of that budget can you cut before the difficulty model starts lying? It turns out the real judge itself picks up a compression bias, discovered by running the actual pipeline rather than assuming the judge is neutral.

## What the studies found

### S1: difficulty compression weakens the signal, it does not flip it

The generator emits a difficulty prior per task (trajectory length times arg richness). I compressed and stretched it by a scale factor. **This table changed after the audit**: the previous version reported a sign flip at low compression ("the model lies"); that result doesn't replicate once the Spearman tie-averaging bug and the generator's duplicate-signature bug are both fixed.

| scale | calibration monotonicity (corrected) | calibration monotonicity (original, before the audit) | split predictability |
|---|---|---|---|
| 0.1 | -0.128 | +0.26 (claimed sign flip) | 0.8 |
| 0.3 | -0.058 | +0.22 (claimed sign flip) | 0.9 |
| 0.6 | -0.297 | -0.13 | 0.95 |
| **1.0** | **-0.688** | -0.59 | 1.0 |
| 1.5 | -0.726 | -0.56 | 1.0 |
| 2.0 | -0.430 | -0.12 | 1.0 |

The corrected result is more modest and, honestly, more boring: compression **weakens** the calibration signal (monotonicity drops from -0.69 at natural scale to -0.06 at 10x compression) rather than inverting it. The parameter is still load-bearing: a benchmark generator with heavily compressed difficulty is still a worse benchmark generator, it just isn't the dramatic "the model actively lies" failure mode the buggy measurement reported. What actually produced that sign flip: a tie-blind Spearman implementation combined with a generator that had structural duplicate collisions, both fixed in this pass (see the audit note above). Split predictability's robustness (0.8-1.0 across the whole sweep) is unaffected by either bug and holds up as reported before.

### S1: the human calibration bar has a Goldilocks zone

Varying the human population's skill (the oracle's d0). This table's shape was already correct before the audit and is essentially unchanged by the fixes:

| d0 | pass rate (2-of-10) | calibration monotonicity |
|---|---|---|
| 0.2 | 0.37 | -0.567 |
| 0.35 | 0.66 | -0.675 |
| 0.5 | 0.92 | **-0.688** |
| 0.65 | 0.99 | -0.575 |
| 0.8 | 1.00 | -0.498 |

If everyone passes (d0=0.8) or most fail (d0=0.2), the calibration signal degrades. There's a real operating window. ARC's "most candidates rejected" intuition turns out to be a measurable curve.

### S2: how many tasks until the benchmark stops wobbling?

Sample-size scaling, the honest sampling-marginal: draw random subsets, score, repeat. Greedy solver's score variance vs subset size:

| tasks | greedy RHAE (mean ± stdev) |
|---|---|
| 30 | 0.316 ± **0.064** |
| 60 | 0.360 ± 0.050 |
| 120 | 0.328 ± 0.053 |
| 240 | 0.304 ± 0.028 |
| 480 | 0.316 ± **0.014** |

Variance drops roughly 4.6x from 30 to 480 tasks (previously reported as ~6x, a real but modest change from the generator and RHAE fixes, same conclusion). Below ~100 tasks, a benchmark's score is noise with a mean. This is METR's evals-as-scaling applied to benchmark construction. A benchmark isn't trustworthy until you've measured how much benchmark you need.

### S3: structural features predict human solvability better than the buggy pipeline reported

K-fold cross-validation of the difficulty model (fit on train folds, measure rank correlation between fitted difficulty and measured solve rate on held-out folds). **This is the other finding that reversed.** The original claim, "structural features can't predict human solvability, you need the calibration oracle, the difficulty model overfits," turns out to have been substantially a measurement artifact:

| feature set | out-of-fold (corrected) | out-of-fold (original, before the audit) |
|---|---|---|
| all features (calls + tools + arg complexity) | **-0.662** | -0.15 |
| n_calls + n_tools | -0.634 | n/a (collinear with n_calls alone before the fix) |
| n_calls only | -0.418 | -0.18 |
| arg complexity only | -0.345 | -0.19 |
| n_tools only | -0.323 | n/a (identical to n_calls before the fix) |

In-sample on the same 230-task pool: **-0.685**. Out-of-fold: **-0.662**. That's a 0.02 gap, not the 0.44 gap ("-0.59 in-sample vs -0.15 out-of-fold") originally reported. The original comparison was apples-to-oranges besides: it compared S1's in-sample number, fit on a *different* 120-task pool with the full pipeline's gauntlet and calibration bar applied, against S3's out-of-fold number on a differently-constructed 230-task pool with neither. Once the same pool is used for both sides, **the difficulty model generalizes almost perfectly.** Two bugs drove the original overstated gap: a tie-blind Spearman correlation (biasing every number in this table), and a generator defect where `n_calls` and `n_tools` were mathematically identical for every task (the tool-sequence generator never repeated a tool within one task), so the "single-feature ablation" was silently testing the same feature twice under two names. Fixing the second bug is also why `n_tools_only` and `n_calls_only` are different numbers now: a real ablation, not a collinear one.

The honest, corrected finding: on this task domain, simple structural features (how many tool calls, how many distinct tools, how much argument complexity) predict human solve rate well, and they generalize out of fold. That's a real result, and it's the opposite of what a benchmark builder should want to hear if the goal is "you must run real humans, structural proxies are worthless": the proxies aren't worthless here. Whether that generalizes beyond this deliberately simple tool-use domain to something ARC-AGI-3-scale is genuinely open; simple domains may just have easy-to-learn difficulty surfaces. ARC still runs 400 humans through 2,893 attempts, and that's still the right call for a domain where the difficulty surface isn't this legible. But "the calibration oracle is the *only* thing that grounds the difficulty axis" was too strong a claim from this data, and the data said so once measured correctly.

### S4: a contamination monitor you can actually validate

The leak probe fires when a task's value-level signature appears in an **independently-built** knowledge base. A prior version built that knowledge base from the same task population being tested, which made "fire on leaked" trivially guaranteed by construction rather than a measured detection event. Fixed: the knowledge base now comes from a disjoint, separately-generated reference pool, and "leaked" tasks are deliberately mutated to match entries drawn from it.

| leaked fraction | fire on leaked | false-fire on clean |
|---|---|---|
| 5% | 1.000 | 0.0000 |
| 10% | 1.000 | 0.0000 |
| 20% | 1.000 | 0.0000 |
| 30% | 1.000 | 0.0000 |
| 50% | 1.000 | 0.0000 |

Detection is perfect at every leak rate with zero false-fires, actually cleaner than the previous (tautological) version, which reported a slowly-growing false-fire rate (0.0054 at 20%, 0.0087 at 50%) that turned out to be an artifact of the generator's duplicate-signature bug, not a real property of the detector. Now that duplicates are gone and the knowledge base is genuinely external, the monitor's operating curve is real, not decorative.

### S4b: the real-surrogate contamination probe

S4 validates the leak-probe *mechanism*. This asks whether a real model actually leaks. `run_llm_leak_probes` sends a real model (DeepSeek `deepseek-chat`) a task's structural hint (tool names and argument keys only, every value withheld) and checks whether the completion reproduces the withheld values anyway, with a word-boundary match, not a bare substring check (a prior version would count a value of `3` as "reproduced" by any text containing the digits `13`). That's the literal Gemini-3 scenario from the ARC report: a model that "knows" content it was never shown.

Across 20 never-leaked tasks against a model that has never seen this benchmark (it can't have: these tasks are generated fresh, per run, from a mock tool registry that doesn't exist anywhere on the public internet): **0 of 20 probes fired, 0 network failures.** The first run of this pass actually hit 6/20 timeouts against DeepSeek, which the fix in this same audit pass (logging completions and failure counts explicitly, instead of letting a timeout produce the same "fired=False" as an honest answer) is what caught. Rerun with a longer timeout, the result is clean: false-fire rate 0.0000, matching S4's synthetic clean-baseline exactly, and this time verifiably a real measurement, not a partially-masked outage. Code: [`s4b_real_surrogate.py`](https://github.com/caiotheodoro/substrate/blob/main/apps/trust/py/src/trust/forge/studies/s4b_real_surrogate.py), [`run_llm_leak_probes`](https://github.com/caiotheodoro/substrate/blob/main/apps/trust/py/src/trust/forge/contamination.py).

### S6: how much human-attempt budget does a judge save you?

Directly extends Airbnb's judge-calibration loop into a budget question: if a calibrated LLM judge pre-screens which tasks are unambiguously easy or hard from the prompt alone (no trajectory, no oracle), how many of the 10 human attempts per task can be skipped before the difficulty model starts lying? The judge here is a real model (DeepSeek), not simulated.

| screening threshold | tasks auto-resolved | budget used | calibration monotonicity |
|---|---|---|---|
| 0.0 (no screening) | 0/60 | 100% | -0.789 |
| 0.1 | 9/60 | 85.0% | -0.789 |
| 0.2 | 14/60 | 76.7% | -0.789 |
| 0.3 | 46/60 | 23.3% | -0.634 |
| 0.4 | 46/60 | 23.3% | -0.634 |
| 0.5 (max screening) | 60/60 | 0% | -0.522 |

The expected result: a real judge saves real budget, and cleanly this time. Thresholds 0.1-0.2 cut 15-23% of the human-attempt budget at **zero** monotonicity cost (-0.789, identical to the unscreened baseline, not just "close"). The unexpected one, unchanged by the audit fixes: **the real judge's own score distribution is compressed.** Across all 60 tasks it never rated anything above 0.6 on a 0-1 difficulty scale, so it has no confident "hard" tail, only a "trivial" one and an undifferentiated middle. That's why the budget drops so sharply between thresholds 0.2 and 0.3 (14 → 46 auto-resolved), and why monotonicity only degrades moderately even at maximum screening (-0.522, not collapsing to zero): the judge is applying a compression pattern to itself, similar in shape to what S1 originally (mis)measured in the synthetic generator, a coincidence worth naming honestly rather than papering over, given S1's own version of that pattern didn't survive the audit. A judge's difficulty ratings still deserve the same sensitivity check S1 applies to the generator; that discipline is the actual point, independent of whether this particular echo turned out to be as dramatic as first thought.

One more honest note this table forced: rerunning this study against the live DeepSeek API twice produced slightly different auto-resolved counts each time (9 vs an earlier run's 8, 14 vs 12) even at temperature 0. The rest of this pipeline is byte-reproducible by construction; a real judge calling a real API is the one place that guarantee doesn't hold, and the numbers above are from the run that actually landed in the committed artifact, not an average or a cherry-pick. Code: [`s6_judge_ladder.py`](https://github.com/caiotheodoro/substrate/blob/main/apps/trust/py/src/trust/forge/studies/s6_judge_ladder.py).

### The real-LLM run: the first honest human-vs-AI point on this benchmark

Every number above compares synthetic solvers (random, greedy, perfect) against each other or against the simulated oracle. None of it says anything about a real system. `LlmSolver` (an OpenAI-compatible bridge already in the codebase) was wired to DeepSeek's `deepseek-chat` endpoint and run against the live benchmark, with two fixes that changed what this run could even measure: bearer-token auth (it previously had none, so real endpoints silently failed every call), and recovery from a single bad tool call (a prior version treated one hallucinated tool name the same as a dead endpoint, an instant episode failure, instead of a wasted action the agent could still recover from).

| solver | solve rate | RHAE |
|---|---|---|
| random | 0.0% | 0.000 |
| greedy (prompt-following heuristic) | 25.8% | 0.258 |
| **DeepSeek (real model)** | **95.2%** | **0.952** |
| perfect | 100% | 1.000 |

DeepSeek solved 95.2% of the 75-task run (62 survived the gauntlet + 2-of-10 calibration bar) at RHAE 0.952, up from an earlier, bug-affected run of this same pass that reported 90.7%. Both the gauntlet and the RHAE computation changed under it since that number, so they aren't directly comparable; this is the first number produced by the corrected pipeline. Split predictability on this particular 62-task calibrated population came in at 0.7 (below the 0.8 acceptance bar), a real instance of S2's own lesson: a calibrated population this size is genuinely too small for a stable predictability read, not a new defect. A local Ollama endpoint was not available in this environment to run the same comparison against a smaller open-weight model; see honest limits below. Code: [`LlmSolver`](https://github.com/caiotheodoro/substrate/blob/main/apps/trust/py/src/trust/forge/agents.py), run artifact: [`benchmark-agentic-tooluse-deepseek.json`](https://github.com/caiotheodoro/substrate/blob/main/docs/validation/benchmark-agentic-tooluse-deepseek.json).

## The absorption thesis, revisited honestly

The core claim is "benchmarks die of absorption, not saturation." The previous version of this section leaned on S1's sign-flip and S3's overfitting gap as the mechanism-level evidence distinguishing absorption from saturation. Both of those specific results didn't survive the audit, so that argument doesn't stand as written, and I'm not going to rebuild a version of it that happens to fit whatever data is left. Here's what the corrected data actually supports and doesn't.

What holds: the pipeline's own difficulty axis is real and predictable (S3, corrected), which means when a difficulty model's calibration *does* break, on a domain this legible, that's a meaningful signal rather than noise from an inherently unmeasurable axis. What's still true and load-bearing: split predictability is robust across every parameter stress test in this pipeline (0.8-1.0 throughout S1's corrected sweeps), a real, boring, useful canary property. Public and private splits stop predicting each other when something upstream breaks, full stop, independent of the absorption-vs-saturation framing.

What I no longer have clean evidence for: a mechanism-level signature that distinguishes "absorbed" from "saturated" *within this pipeline's own instrumentation*. The ARC report's Gemini-3 anecdote (a verification model using a color mapping it was never told) is still the clearest real-world example of absorption as a distinct phenomenon from raw capability saturation, but this project's own studies, once measured correctly, don't add a new quantitative signature on top of that anecdote. That's a narrower claim than the original version made, and it's the honest one.

## SOTA evals literature: what's changed since ARC and Airbnb

Beyond ARC-AGI-1/2/3, JudgeBench, and METR (all already load-bearing above), four threads from 2025-2026 evals research bear directly on what the Foundry does and doesn't yet cover:

- **Agentic trajectory evaluation.** Recent work (a 2026 survey on LLM-based agent evaluation, and specialized tools like TrajAD for runtime trajectory-anomaly detection) has moved past "final answer correct?" toward step-level trajectory scoring: tool choice, argument correctness, decision order, and *when* an agent should have stopped but didn't. The Foundry already does the strong version of this for free. `exact_trajectory_verifier` and `reference_run_verifier` check the full call sequence, not just the outcome, and RHAE's action-count penalty directly punishes an agent that "looks busy" without being efficient, a claim that's now actually backed by a non-degenerate metric (see the audit note above), not just a formula that happened to match ARC's on paper. What it doesn't do yet is anomaly *localization* mid-run (TrajAD's contribution); the Foundry's verifiers are binary pass/fail on the completed trajectory, not per-step diagnostics.
- **Reward hacking and verifier gaming under RL.** 2026 work on RLVR ("LLMs Gaming Verifiers," reward-hackability audits of code-RL training environments, adversarial hacker-fixer loops for hardening agent benchmarks) documents models that learn to exploit *what the verifier fails to enforce*: monkey-patching test harnesses, deleting assertions, exploiting credit leakage from spurious reasoning traces. This is the generate-verify-train loop from the ARC report, formalized: a measured training dynamic, not a hypothetical one. The Foundry's verifiers are programmatic and check exact trajectories/values, which closes the most common hacking surface (a model can't monkey-patch a Python assertion it never has access to). But nothing in the pipeline currently tests whether a *solver* under a training loop (not just a one-shot eval) starts exploiting the verifier's specific matching logic instead of solving the task. That's untested, and it's the single most important gap this literature surfaces.
- **Contamination detection beyond n-gram matching.** 2026 work (DyePack's backdoor-based flagging, distributional and black-box sample-level detection methods) responds to a real weakness: n-gram and exact-match detection misses rephrased or paraphrased leaked content entirely, and gets more expensive as pretraining corpora grow. The Foundry's contamination monitor (S4/S4b) is value-level signature matching, which is closer to DyePack's spirit than plain n-gram (it matches the *structural fingerprint* of a solution, not just prose overlap). But it has no defense against a model that reproduces the right values in a *rephrased* structure, and no backdoor-style provable-flagging mechanism. Both are natural S7/S8 candidates.
- **LLM-as-judge reliability.** "Reliability without Validity" is part of a larger 2025-2026 body confirming judges are unreliable in specific, structural ways: position bias strongly tied to the quality gap between compared outputs, no judge uniformly reliable across benchmarks, frontier judges failing over half of dedicated bias tests. S6's finding, that the real judge's own difficulty ratings are compressed and never use the top of its scale, is a small, concrete instance of exactly this literature's warning, caught empirically. That's the point of building the pipeline instead of just citing the papers, and it's also exactly the kind of claim that needs the same adversarial scrutiny this whole pass applied to everything else. That's why this section leads with the audit rather than treating any single study's result as self-certifying.

## What the evolution taught

1. **Publish the audit, not just the numbers.** An adversarial pass on this project's own pipeline found two bugs that had inverted or overstated the two most "interesting" findings in the original version of this piece. Sensitivity analysis on inherited parameters (the original point of this project) and adversarial code review on your own measurement code are the same discipline aimed in two directions, and skipping the second one meant publishing a sign flip and an overfitting claim that were substantially bugs.

2. **A tie-blind rank correlation is a silent, structural bias, not a rounding error.** Every headline number in this pipeline goes through Spearman correlation, and the fitted difficulty values are heavily tied in practice. An estimator that breaks ties by array index instead of averaging them doesn't fail loudly; it just quietly reports a different number, in a direction that depends on the tie structure, not the underlying relationship.

3. **A metric can look right on paper (formula matches ARC's exactly) and still measure nothing in practice.** RHAE's math was correct; the human-baseline generation that fed it was decoupled from the thing being measured, so the metric always saturated its own cap. Verifying a formula against its citation isn't the same as verifying the pipeline that feeds it.

4. **The stratification property is still the most reliable canary in this pipeline.** Split predictability survived every parameter stress test, before and after the audit (0.8-1.0 throughout). When a benchmark's public and private splits stop predicting each other, something upstream broke, and the difficulty model is still the first suspect.

5. **Reproducibility is free if you design for it, verified twice now.** The entire pipeline, from generation to scoring, is byte-reproducible across seeds by construction, and every fix in this pass was verified against a fresh, from-scratch regeneration of every artifact, not a diff of what changed.

6. **You can validate a contamination monitor, including catching your own tautologies.** The first version of S4's monitor validated correctly *by construction*: the "leaked knowledge base" was built from the same tasks it tested, so a leaked task matching itself was guaranteed, not measured. Fixed to check against a genuinely external reference corpus, it's now a real detector with a real operating curve.

7. **A judge saves real budget, cleanly, once the measurement is trustworthy.** S6's real-DeepSeek judge cut human-calibration spend by 13-20% at zero monotonicity cost, cleaner than the "essentially no cost" the pre-audit version reported, because the underlying correlation estimator is no longer biased. It's Airbnb's "measure judge agreement" principle, applied against this pipeline's own attempt-budget cost function.

## The honest limits

The human oracle is still simulated for the main benchmark run. Real-human calibration now has infra behind it ([`CalibrationQueue` / `RealHumanOracle`](https://github.com/caiotheodoro/substrate/blob/main/apps/trust/py/src/trust/forge/calibration_queue.py), protocol-conformant with `SimulatedOracle` and now honoring its `n_attempts` argument correctly, proven by a mock-backed integration test), but zero live human data. That is the biggest remaining gap, and it is deliberately not faked here: `RealHumanOracle.calibrate()` raises instead of fabricating an outcome for a task whose attempt quota isn't met.

The real-LLM run used DeepSeek only. A local Ollama endpoint, for a comparison against a smaller open-weight model, was not available in this environment. The run that would produce that comparison is queued as the natural next step, not run.

S4b's real-surrogate contamination probe reports a clean (0% false-fire, 0 network failures) baseline on a model that has genuinely never seen this benchmark. It says nothing about detection on a model that *has* leaked, which requires either an actual leak event or a deliberate fine-tune, neither of which happened here.

S3's reversed finding (structural features predict difficulty well) is measured on a deliberately simple, single-domain task space. Whether it generalizes to harder or more heterogeneous domains, where a difficulty surface might genuinely not be structurally legible, is open, and is exactly the kind of claim this project's own audit discipline says shouldn't be asserted without measuring it there too.

Harder task domains (compositional multi-step, retrieval-grounded, classification), the generality question of whether this methodology transfers beyond tool-use, were explicitly scoped out of this pass. The task domain remains narrow by design: tool-use over a mock registry, so the methodology stays the subject, not the tasks. The benchmark itself is still not competitive with ARC's in difficulty. It's a proof that the methodology runs end-to-end with every property measured, now including an adversarial audit of the measurement itself, which is the property that was missing before.

---

All studies are reproducible: `uv run python -m trust.forge.studies.s1_sweeps` (and s2/s3/s4/s5/s6), `uv run python -m trust.forge.studies.s4b_real_surrogate --tasks 20` (needs `MODEL_PROVIDER_BASE_URL`/`MODEL_PROVIDER_MODEL_ID`/`MODEL_PROVIDER_API_KEY`), artifacts in `docs/validation/studies/`. The real-LLM benchmark run: `uv run python -m trust.forge.cli bench --llm --llm-base <endpoint>/v1 --llm-model <model> --llm-name llm-<label>`.
