# substrate

A monorepo of five agent-systems research units. Each unit is a reference
implementation plus its benchmark harness, built so the claims behind it can
be measured and falsified rather than asserted.

The core idea: agents fail in production not because the base model is wrong
on average, but because a specific wrong decision ships undetected. Each unit
attacks one piece of that problem and feeds the others through shared
contracts.

## Units

| Unit | What it is | Ports |
|---|---|---|
| `apps/harness` | Deterministic, gated, replayable agent runtime. Records every decision as an event-log row, gates tool calls (execute / escalate / reject), and replays runs byte-identically in CI. | 8930–8941 |
| `apps/trust` | Measurement discipline for confidence: an evidence-based scorer (ConfBench), a gated-data pipeline, and a recalibration loop over the decision log. Bans self-report (logprobs, verbalized confidence) as a feature — measures them only as baselines. | 8000–8060 |
| `apps/efficiency` | Token economics: cost ledger, cache analytics, confidence-gated routing, wire discipline (RFC 6902 deltas, cache-stable prompt blocks), marginal-token-utility harness, TCO model. | 8100–8104 |
| `apps/knowledge` | Retrieval operated like a database: corpus characterization, typed extraction, entity resolution, graph/vector store, freshness, and a grounded gate that returns support / contradict / silent verdicts. | 8201–8204 |
| `apps/simulation` | Synthetic worlds and calibration baselines: SimBench retro-validation against real shocks (2025 is holdout), presence-vs-turn-based probes. | 8300–8303 |

Shared code lives in `packages/substrate` (the C1–C7 contracts: event log,
decisions, retrieval verdicts, cost ledger, confidence API, scenarios, wire
discipline; plus the eval core) and `packages/scenarios` (shock seeds).

The units are wired together over HTTP at the seams — the harness gates
against trust's scorer, retrieval verdicts flow from knowledge into trust's
features, and the efficiency ledger records harness steps. The seam tests
(`apps/harness/src/test/seam-e2e.test.ts`) run one decision through all four
units with real services.

## Research: the Calibrated Evaluation Foundry

Inside `apps/trust/py/src/trust/forge/` sits a second research thread, built
on top of the trust unit rather than parallel to it: a reproduction of
ARC-AGI-3's benchmark-construction methodology, then a study harness that
stress-tests the methodology's own parameters instead of taking them on
faith.

**The premise.** ARC-AGI-1 survived five years of scaling; ARC-AGI-2 lasted
months. ARC-AGI-3's technical report names the failure mode: a benchmark
stops measuring anything once its task space gets absorbed by a
generate-verify-train loop, not once it's merely solved. Their fix was a
production methodology, not a harder static test — human-calibrated
difficulty (every task attempted by 10 humans, solved by ≥2), a
random-policy floor (1 in 10,000), efficiency scoring against human
baselines, and private splits structurally out-of-distribution from public
ones. Every number in that methodology was inherited from somewhere, and
nobody had published which of them actually matter for the resulting
benchmark's validity.

**What's built.** The full pipeline — generate → gauntlet → calibrate → fit
difficulty → stratify splits → score solvers → monitor contamination — plus
six parameter studies (S1–S6) that vary the pipeline's own knobs and measure
what breaks. All of it is deterministic, offline, and byte-reproducible by
construction.

**What it found**, with real numbers, not simulated ones where a real model
was available:

| Study | Question | Finding |
|---|---|---|
| S1 | What happens if the difficulty signal is compressed? | The fitted model doesn't degrade gracefully — it **inverts sign** and reports harder tasks as easier, with high confidence |
| S2 | How many tasks before a benchmark's score stops being noise? | Variance drops ~6x from 30→480 tasks; below ~100, a benchmark's score is noise with a mean |
| S3 | Can structural features (call count, arg complexity) predict human solvability? | No — in-sample fit -0.59, out-of-fold -0.15. The difficulty axis needs a real calibration oracle, not a proxy |
| S4 / S4b | Does the contamination monitor actually detect leaks, real model included? | Perfect detection across synthetic leak rates (S4); 0/20 false-fire against a real, never-leaked DeepSeek run (S4b) |
| S6 | How much human-calibration budget does a real LLM judge save? | 10–18% of attempt budget, free — and the real judge's own difficulty ratings turned out compressed in the same shape S1 found synthetically |
| bench | What does a real frontier model score on this benchmark? | DeepSeek: 90.7% solve rate, RHAE 0.907 (vs. greedy 0.24, perfect 1.0) — the first real-model number this pipeline has produced |

Full writeup, the SOTA-evals literature it sits against, and the honest
limits (simulated human oracle for the main run, no local Ollama comparison
yet): [`docs/blog-eval-foundry.md`](docs/blog-eval-foundry.md). Build
history, premises, and the complete results ledger:
[`docs/HANDOFF.md`](docs/HANDOFF.md). Code:
[`apps/trust/py/src/trust/forge/`](apps/trust/py/src/trust/forge/).

```sh
cd apps/trust/py
uv run python -m trust.forge.cli bench --tasks 300 --seed 7
uv run python -m trust.forge.studies.s1_sweeps   # and s2/s3/s4/s6
```

## Prerequisites

- Node 24, pnpm 10
- Python 3.11+ with [uv](https://docs.astral.sh/uv/) (trust, knowledge, simulation)
- Docker (compose profiles; services are optional — all tests run offline)

## Run the tests

```sh
pnpm install
make validate        # compose configs + typecheck + every TS and Python suite
```

Per unit:

```sh
pnpm -r test                           # TS: substrate, scenarios, harness, efficiency, simulation
cd apps/trust/py && uv run pytest
cd apps/knowledge/py && uv run pytest
cd apps/simulation/py && uv run pytest
```

The harness suite includes cross-language e2e tests that spawn real Python
services from the trust/knowledge venvs, so run it with the venvs in place
(`uv sync` in each `apps/*/py` first).

## Run a stack

```sh
make up profile=trust        # or: harness, efficiency, knowledge, simulation
```

Each profile brings up that unit's services plus the shared atoms it needs
(Postgres, Redis, MinIO, Ollama). Profiles bind shared ports (5432, 11434,
9000 …), so run one at a time. Per-unit runbooks: `apps/<unit>/BUILD.md`.

## Validate a claim

The benchmarks write their evidence to `docs/validation/`:

- `r1_dominance.json` — evidence-based scoring vs self-report under
  distribution shift (Brier / ECE / NDCG-escalation)
- `judge-drift.json` — reference-regeneration and judge-drift rates, and
  the effect of the eval cache on both
- `judge-calibration.json` — judge agreement vs human labels (Cohen's
  kappa / Krippendorff's alpha) with a disagreement breakdown
- `uncertainty-decomposition.json` — epistemic vs aleatoric split across a
  judge ladder

The Foundry writes its own evidence to `docs/validation/studies/`
(`s1-*.json` through `s6-judge-ladder.json`) and `docs/validation/`
(`benchmark-*.json`, `s4b-real-surrogate.json`) — see the table above.

## Conventions

- Versioning: `v1` = operable loop (built), `v2` = listed, not built.
- LLM access goes through OpenAI-compatible clients (Ollama by default);
  frontier models are env-keyed for validation only, never a runtime
  dependency.
- Every unit ships its benchmark; a claim without a measured baseline
  against it is not done.

See `docs/PLAN.md` for the contracts, port map, and build history.
