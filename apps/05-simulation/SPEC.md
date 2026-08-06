# 05 · Simulation — Calibrated Behavioral Simulation

## Thesis

Every major forecasting approach of the last thirty years shares one premise: the future is legible from the past. The fitted curve breaks exactly when the underlying dynamics shift — a tariff announcement, a surprise Fed decision, a viral sentiment cascade. The 4.2% MAPE collapses to 35% off the week a shock hits. Meanwhile, the alternative — behavioral simulation — is plausible always and **validated never**: no one has run a swarm simulation against the 2020 pandemic, the 2021 supply chain crisis, the 2022 inflation spike, the 2025 tariff waves, and measured whether the simulated emergent behavior matched what actually happened.

On the social side, the same disease appears one level up: multi-agent systems schedule agents like queue servers, round-robin, forever, and the result never feels like a room of people — nobody lurks, nobody misreads silence, nobody's *absence* is information.

**Simulation is the unit that makes behavior — economic and social — measurable.** A retro-validation benchmark (SimBench) that scores simulation against history, and a presence engine that replaces turn-based scheduling with urge-driven behavior — both calibrated, both falsifiable.

## Why it matters

- **Forecasting's blind spot is the inflection point.** Statistical models are right on average and wrong at the moments that matter. Simulation models the generative system (agents reacting to each other) instead of fitting its output curve — but without validation it's theater. The field needs the missing piece: **the benchmark that scores simulation against history** — the difference between an interesting architecture and a trustworthy one.
- **Believable actors are the load-bearing wall of every simulation product.** Social platforms, market simulations, synthetic-user panels, negotiation practice — all of them die if the agents' social behavior is not believable, and turn-based scheduling is the #1 believability killer.
- **The two halves share a method.** Retro-validation is the Brier-score discipline from superforecasting, applied to emergent systems; believability probes apply the same "measure against a baseline" discipline to social behavior.

## Core concept

### Calibration for emergent systems

For a system that generates a distribution of futures, calibration means:

- **Retro-validation.** Run each scenario against a *known* historical shock and measure whether the simulation's distribution covered the realized outcome (coverage at 50/80/95%), plus Brier-style reliability at the scenario level.
- **Confidence honesty.** The simulator must be able to say "stable scenario set" vs "honestly, wide spread." A static model betrays this the moment the world shifts; the simulation gets to be honest — if it's measured.

### The hybrid framing

Neither approach works alone. The **hybrid**: the statistical model provides the baseline point estimate; the simulation provides the scenario distribution and the behavioral uncertainty band around it. The finding will not be "simulation wins" — it will be *the partition*: on which shock categories the scenario band beats the statistical CI (social cascades, sentiment contagion), and on which it loses (steady-state operations).

### Urge-driven behavior, not turns

Replace round-robin scheduling with agent behavior driven by **attention, interpretation, motivation, emotion, pressure, inhibition, and memory**:

- Attention — the agent notices what it attends to, not everything.
- Emotion — Russell's circumplex state that shifts thresholds.
- Pressure & inhibition — the mechanism that makes *silence meaningful*: an agent that is pressured to respond but inhibited from responding *is* producing behavior.
- Initiative engine — moves driven by urgency, not queue position.

## Ecosystem role

- **Feeds to 02:** synthetic worlds — the source corpus for gated synthetic-data generation (the Trust unit's data side).
- **Feeds to 01:** stress scenarios — injected shocks used by the Harness to measure how gating behaves under distribution shift.
- **Consumes from 04:** corpus properties and extraction quality as dimensions for building document-grounded simulation worlds.
- **Consumes from 02:** calibration and verification discipline — the same "measure against outside evidence" standard.

## What gets built

1. **SimBench** — an open benchmark harness for behavioral forecasts. Replays known historical shocks (2020 pandemic demand, 2021 supply chain, 2022 inflation, 2025 tariff waves) and scores any simulation engine on coverage, calibration, tail behavior, and value-vs-baseline (LightGBM/ARIMA) at the break.
2. **The hybrid reference implementation** — statistical baseline + swarm simulator sharing the same tasks, evaluated on SimBench, with an honest accounting of *when simulation beats baseline and by what margin*.
3. **Seed-material synthesizer** — automated macro (FRED-style) data → narrative "state of the world" documents: world-building, not regression inputs.
4. **Injection library** — a growing family of shock scenarios replayable as standardized interventions.
5. **The presence engine** — reference implementation of urge-driven agent behavior (continuation of Perfectman): per-agent attention/emotion/pressure/inhibition computation, initiative engine, no global scheduler.
6. **Believability probes** — measurement instruments: behavioral (interruption rate, lurking rate, response-latency distribution, silence-misreading rate, alliance formation) plus human-judged "does this feel like a room of people?"

## Architecture sketch

```
baseline stats model (LightGBM/ARIMA) ─┐
                                       ├─► hybrid forecast + scenario band
simulation (agents, world-seed,   ─────┘
         injection library)
              ▼
        SimBench evaluation
   for each historical shock R:
      coverage at 50/80/95 · Brier · tail-loss vs baseline
              ▼
    report: when does simulation win? when does it lie?
```

```
agent
  ├─ attention → what it notices
  ├─ interpretation → meaning of what it noticed
  ├─ motivation → goals (drives initiative)
  ├─ emotion → circumplex state (drives thresholds)
  ├─ pressure/inhibition → when to act, when to stay silent
  └─ memory (temporal) → social history, alliances
           ▼
     initiative engine (no round-robin; urgency-driven)
           ▼
     events (posts, replies, lurk, alliance) → social log
           ▼
     believability probes + spectator view
```

## Research program

- **R1: The retro-validation study.** Run a swarm simulator against the 2020–2025 shocks with honest seed material and measure: does the emitted distribution actually cover the realized demand? The field lacks this benchmark — and it will honestly report how much of a shock's shift is simply non-coverable, even with hindsight.
- **R2: Where does the hybrid actually win?** The partition: shock categories where the scenario band beats the statistical CI vs where it loses.
- **R3: Seed-material sensitivity.** How output distribution changes with seed prose — where quality drops: world coherence or persona resolve?
- **R4: The absence signal.** Can the information carried by *not responding* be measured and made legible? Latency distributions, silence-as-negotiation, misreading-of-silence.
- **R5: Emergent structure without scripts.** Under pure pressure/inhibition mechanics, which social phenomena actually emerge without being written — alliance formation, scapegoating, norm enforcement — and which need explicit drives? Pre-committed, with scripted-ness detected by the probes.
- **R6: Calibration to human baselines.** The distributional gaps vs human rooms (interruption timing, reply latency, topic persistence) — SimBench discipline applied to social behavior.

## Risks / failure modes

- **The "feels right" trap.** A simulation that is plausible and never checked produces the most dangerous confidence — plausible wrongness. SimBench exists to keep this a live failure.
- **Tuning to retro-shock fit.** If seed material is tuned until the simulator looks good on history, you've overfit — exactly the static-correlation assumption being escaped. Discipline: hold out a shock category end-to-end (seed/calibrate on 2020–2022, validate unconstrained on the 2025 tariff wave).
- **Emergence theater.** Hand-rolled phenomena dressed as emergence. The research pre-commits to which phenomena are claims of emergence (R5).
- **The uncanny room.** Agents that are "too social" read as chaos, not presence. Pressure/inhibition is the tuning dial, and its calibration is research, not taste.
- **Cost ceiling.** LLM cost for thousands of SKUs daily still explodes. Where is the cost/rounds frontier that makes daily simulation viable — tiny+frontier hybrids, agent pruning, population-slice-and-scale?

## Success signals

- SimBench exists with the retro-validated benchmark published; a specific coverage/calibration claim that reproduces across simulators.
- The hybrid shows a measured edge on the *cascade* category and an honest null result on steady-state.
- A room of presence-engine agents where an outside observer can watch a full social arc — lurking, misreading silence, an alliance — *without the script having written any of it*.
- Believability probes published with baseline numbers vs turn-based scheduling; the `presence` library plugs into another simulation and measurably improves social-behavior realism.
- The injection library is reused by 01's stress-testing — the ecosystem link proven by use.