# @substrate/simulation

**Calibrated behavioral simulation.** Making behavior — economic and social — measurable. Retro-validated forecasting (SimBench) and the presence engine.

## What it is

Statistical models are right on average and wrong at the moments that matter. Behavioral simulation models the generative system instead — but is validated never. This unit fixes both halves:

- **SimBench** — replays known historical shocks (2020 pandemic, 2021 supply chain, 2022 inflation, 2025 tariffs) and scores any simulator on coverage, calibration, tail behavior, and value vs a LightGBM/ARIMA baseline.
- **The hybrid** — statistical point estimate + simulation scenario band. The finding is *the partition*: which shock categories simulation covers, which it doesn't.
- **Presence engine** — urge-driven multi-agent behavior (attention, emotion, pressure, inhibition — no round-robin), continuing the Perfectman work.

## Benchmarks

- **Retro-validation** — coverage at 50/80/95% + Brier reliability, with a held-out shock category (no retro-shock overfit).
- **Believability probes** — behavioral (interruption, lurking, silence-misreading, alliance formation) plus human-judged, vs a turn-based baseline.

## Ecosystem

- Feeds synthetic worlds to `02-trust`'s data gates and stress scenarios to `01-harness`.
- The scenario library lives in `@substrate/scenarios`.

## State

Spec written (`SPEC.md`). No implementation yet.