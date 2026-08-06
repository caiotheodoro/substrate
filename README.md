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

## Conventions

- Versioning: `v1` = operable loop (built), `v2` = listed, not built.
- LLM access goes through OpenAI-compatible clients (Ollama by default);
  frontier models are env-keyed for validation only, never a runtime
  dependency.
- Every unit ships its benchmark; a claim without a measured baseline
  against it is not done.

See `docs/PLAN.md` for the contracts, port map, and build history.
