# 05 · SimBench — Calibrating Simulation-Based Forecasting

## Thesis

Across the entire history of mainstream forecasting, every major approach has shared one premise: the future is legible from the past. The forecast is a fitted curve, and the model breaks exactly when the underlying dynamics shift — tariff announcements, surprise Fed decisions, viral sentiment cascades. The week a tariff hits, the 4.2% MAPE collapses to 35% off.

**Simulation is the honest tool for behavior; prediction is for what stays static.** The hard problem isn't building yet another statistical forecaster, it's making *behavioral simulation* credible: running it against history, measuring its error, and calibrating its outputs so they can be trusted where the curves break.

## Why it matters

Swarm intelligence engines (MiroFish-style) have real architectural appeal — they model the *generative system* (agents reacting to each other) instead of fitting its output curve. But they lack the one thing forecasting needs to be adopted: **validation and calibration against history.** No one has yet run MiroFish-style simulation against the 2020 pandemic shock, the 2021 supply chain crisis, the 2022 inflation spike, the 2025 tariffs — and measured whether the simulated emergent behavior matches what actually happened. That work is the difference between an interesting architecture and a trustworthy one.

Forecasting has been a fifty-year saga of getting calibrated prediction; the missing space is the calibrated simulation.

## Core concept

### The framing gap

Prediction models: right on average, wrong at the moments that matter. Simulation models: plausible always, unvalidated, uncalibrated at the moments that matter. Neither is usable alone.

**The damning combination is the hybrid**: the statistical model provides the baseline point estimate, the simulation provides the scenario distribution and the *behavioral uncertainty band* around it. The injection mechanism gives you exactly the exogenous-shock testing that breaks static curves: break the news into the simulation and watch the cascade agent by agent.

### What "calibrated simulation" means

For a system that generates a distribution of futures, calibration means:

- **Retro-validation.** Run each scenario against a *known* historical shock and measure how well the simulation's distribution captured the realized outcome (coverage). This is the Brier-score discipline from superforecasting 10 levels up at the "whole system" level.
- **Confidence honesty.** The simulator must be able to say "this is a stable scenario set" vs "this is a wide spread and honestly my uncertainty is large" — a calibration that is betrayed by every static model when the world shifts.

## What gets built

1. **SimBench** — an open benchmark harness for behavioral forecasts. Replays known historical shocks (2020 pandemic demand, 2021 supply chain, 2022 inflation, 2025 tariff waves) and scores any simulation engine on:
   - **Coverage**: did the distribution cover the realized outcome (at 50/80/95%)?
   - **Calibration**: Brier / reliability at the scenario level.
   - **Tail behavior**: how far off are the worst-case scenarios when they matter most?
   - **Value vs baseline**: improvement in loss vs a strong statistical baseline (LightGBM/ARIMA) on the same task *at the break*.
2. **The hybrid reference implementation** — a statistical baseline + swarm simulator sharing the same task, evaluated on SimBench, with an honest accounting of *when simulation beats baseline and by what margin*.
3. **Seed-material synthesizer** — automated FRED/macro -> narrative seed material (world-building, not regression inputs). Structured "state of the world" documents that turn macro series into agent context.
4. **Injection library** — a growing family of shock scenarios that replay as standardized interventions, so any forecast can be stress-tested against the SAME shocks.

## Architecture sketch

```
baseline stats model (LightGBM/ARIMA) ─┐
                                      ├──► hybrid forecast + scenario band
simulation (agents, world-seed,   ─────┘
         injection library)
              ▼
       SimBench evaluation
   for each historical shock R:
      coverage at 50/90/95
      Brier / calibration
      tail-loss vs baseline
              ▼
    report: when does simulation win? when does it lie?
```

## Research program

- **R1: The retro-validation study.** Run a swarm simulator against the 2020–2025 shocks with correct seed material and measure: does the emitted distribution actually cover the realized demand? This is the benchmark the field lacks — and it will honestly report how much of a real shock's demand shift is simply non-coverable, even with hindsight.
- **R2: Where does the hybrid actually win?** On which shock categories does the scenario band beat the statistical CI (social cascades, sentiment contagion) vs. lose (steady-state operations)? The finding is not "simulation wins," it's *the partition*.
- **R3: Seed-material sensitivity** empirically measures how output distribution changes with seed prose. Where does quality drop — the coherence of the world, the resolve of the personas?
- **R4: Cost ceiling.** LLM cost for thousands of SKUs daily still explodes. Where is the cost/rounds frontier that makes daily simulation viable — hybrid tiny+frontier, agent pruning, population-slice-and-scale?

## Prior work it builds on

- Blog: *Why I Stopped Trusting My ARIMA Models and Started Simulating Entire Economies* (the entire premise, architecture, and MiroFish analysis), *When the Problem Is Simulation, Not Prediction*, *LLMs and Time-Series Forecasting*, *What Superforecasters Got Right*, *Calibration*.
- Avenza/Adopt: agent orchestration (Temporal), templated personas, human review.
- Skills: simulation, swarm intelligence, time-series forecasting, calibration, GraphRAG (seed-material world model), synthetic data.

## Risks / failure modes

- **The "feels right" trap.** A simulation that produces plausible scenarios and is never checked produces the *most dangerous* confidence — plausible wrongness. SimBench exists to keep this a live poison. — The #1 risk is a published benchmark that quietly hides where simulation *fails* coverage. The spec's job is to make those failures visible.
- **Tuning to retro-shock fit.** If the seed material is tuned until the simulator looks good on historical shocks, you've overfit to history — exactly the static-correlation assumption this program is escaping. The discipline: *hold out* a shock category end-to-end (seed/calibrate on 2020–2022, validate unconstrained on the 2025 tariff wave).

## Success signals

- SimBench exists with the retro-validated benchmark published; a *specific* claim about coverage/calibration (e.g., "simulation covers the 2020 goods-demand shift at 90% where LightGBM misses by a wide tail") that reproduces across simulators.
- The hybrid shows a measured edge on the *cascade* category and an honest null result on the steady-state.
- A logistics/retail domain artifact: a scenario-planning flow where the decision-maker sees coverage and scenario distribution — not a point forecast — with real outcome logging to close the calibration loop.