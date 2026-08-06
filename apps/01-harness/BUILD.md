# Build · @substrate/harness (01) — Deterministic, Gated, Replayable Agent Runtime

> **Read this file + `docs/PLAN.md` (contracts) + `packages/substrate` (implementation). You do NOT need to read other units' files.** Spec: `apps/01-harness/SPEC.md`.
>
> **Constraint: LOCAL-ONLY Docker Compose. LLM via Ollama default (:11434), peak via env key, never a runtime dependency.**

## Interface contract

**Imports:** `@substrate/substrate` (C1 events, C2 decisions, C5 confidence, C7 wire) · `@substrate/scenarios` (C6, for stress scenarios) · `02-trust` scorer (`POST :8020/confidence`) as the confidence provider, OPTIONAL at v1 (fallback = heuristic features) · `03-efficiency` ledger (`POST :8100/steps`) emits, optional at v1.

**Exports:** event log (Postgres, C1) · decision log via gate server (C2) · HITL via MCP elicitation / WS · scenarios consumed for stress-testing.

## Global decisions (don't relitigate)

- Event store: Postgres-backed v1 (`harness-postgres`), KurrentDB v2.
- Orchestrator: v1 = in-process turn loop (bounded, batched), v2 = Temporal turn workflow (signals = pause/resume).
- Gate at the MCP boundary: `@modelcontextprotocol/sdk` TS, gate interposes in-process on `tools/call`.
- Transport: SSE (:8931, with `Last-Event-ID` resume) + WS (:8932 control) + REST (:8930).
- Golden CI: vitest custom matcher + testcontainers-postgres; recorded-response discipline (replay NEVER re-rolls).
- Sandbox: dockerode, short lease + keepalive + liveness probe, parallel artifact upload never gates "done".

## Port map (allocated)

||| 8930 REST · 8931 SSE · 8932 WS · 8934 gate · 8935 escalations · 8936 sandbox · 8937 mcp · 8938 hitl-dock · 8940 uvx · 8941 web |||

## Molecules & atoms

### M1 — Run Engine (first)

| ID | Atom | Type | Tech | v |
|---|---|---|---|---|
| A-H-03 | `events` append/read lib (canonical JSON, chain hash, idempotency) | lib | TS+pg | v1 |
| A-H-04 | `state` pure fold `fold(events) → RunState` | lib | TS | v1 |
| A-H-05 | `run-engine` (capture never gated; replay suppresses side effects) | lib | TS | v1 |
| A-H-06 | `harness-postgres` (tables: runs, events, decisions, pending_actions, escalations, sandbox_leases, thresholds, cost_ledger) | db | pg17 | v1 |
| A-H-10 | `@substrate/llm` (provider-agnostic; `recordedComplete` = replay mode) | lib | TS | v1 |
| A-H-11 | `harness-ollama` (:11434) | svc | Ollama | v1 |
| A-H-16 | `mock-tools` (echo, fake-clock, file, httpbin, delay, fail-once) | lib | TS | v1 |

**DAG:** A-H-06 → A-H-03 → A-H-04 → A-H-05 → A-H-10/A-H-16.
**DoD:** `events` unit tests (idempotency, canonical encoding, chain); `state` fold tests; run-engine integration test against testcontainers postgres: appends an event stream, replays, drops a duplicate tool result.

### M2 — Orchestration

| ID | Atom | Type | Tech | Deploy |
|---|---|---|---|---|
| A-H-08 | `orchestrator` turn workflow (bounded loop, batched narrative+work, hard cap) | svc | TS (in-process v1), Temporal v2 | v1/v2 |
| A-H-09 | `harness-temporal` (+UI) | svc | Temporal auto-setup :7233/:8233 | v2 only |
| A-H-20 | `hitl-bridge` pause/resume (in-process v1; Temporal signal v2) | lib | TS | v1/v2 |

**DoD:** a bounded 8-turn run with batched bookkeeping completes; a turn exceeds the hard cap and the run ends cleanly (event logged).

### M3 — Gate Server (the MCP boundary)

| WP | Atom | Depends | Deploy |
|---|---|---|---|
| A-H-12 | `gate-core` `gate(confidence, execute, reject)` + threshold-sweep | lib | v1 |
| A-H-13 | `gate-server` `POST /gate/decide` → verdict + C2 decision row | svc :8934 | v1 |
| A-H-14 | `threshold-manager` band config + per-task-type thresholds + Pareto estimator | lib | v1 core / v2 estimator |
| A-H-15 | `mcp-tool-server` `initialize`/`tools/list`/`tools/call` (gated) + elicitation | svc :8937 | v1 |
| A-H-17 | `escalation-surface` queue + approve/reject/veto + SSE push | svc :8935 | v1 |

**DoD:** every MCP tool call passes the gate; verdict + confidenceFeatures written to `decisions`; escalation queue renders proposal+confidence+context.

### M4 — HITL dock

| WP | Atom | Depends | Deploy |
|---|---|---|---|
| A-H-18 | `@substrate/pending-action` (question/form/decision, dock state machine) | lib | v1 |
| A-H-19 | `hitl-dock` UI (all-ready gate, atomic submit, WS) | svc :8938 | v1 |
| A-H-20 | `hitl-bridge` (dock→Temporal signal v2 / in-process v1) | lib | v1/v2 |

**DoD:** a `request_action(kind: form)` mid-turn pauses the run, resolves in dock, run resumes with tool history intact.

### M5 — Sandbox

| WP | Atom | Depends | Deploy |
|---|---|---|---|
| A-H-21 | `sandbox-client` acquire(lease)/keepalive/liveness/exec/artifacts/release | lib | v1 |
| A-H-22 | `sandbox-manager` :8936 (docker.sock, lease table, cadence) | svc | v1 |
| A-H-23 | `sandbox-images` (node + python, bounded I/O wrappers) | script | v1 |
| A-H-24 | `uvx-tool-runner` ephemeral tool exec | svc :8940 | v2 |

**DoD:** lease expires when no keepalive; parallel artifact upload never blocks the "done" signal; liveness probe detects dead sandbox.

### M6 — API/UI

| WP | Atom | Depends | Deploy |
|---|---|---|---|
| A-H-25 | `harness-api` REST/SSE/WS (:8930-32) | svc | v1 |
| A-H-26 | `harness-web` read-only transcript UI (:8941) | svc | v1 minimal |

### M7 — Replay & Golden CI

| WP | Atom | Depends | Deploy |
|---|---|---|---|
| A-H-27 | `@substrate/replay` replay fold, idempotent tool results | lib | v1 |
| A-H-28 | `@substrate/golden` canonical serialization + `toMatchGoldenRun` matcher | lib | v1 |
| A-H-29 | `golden-corpus` committed JSONL (events + recorded LLM + tool results) | dataset | v1 |
| A-H-30 | `ci-golden` vitest + testcontainers CI job | ci | v1 |
| A-H-31 | `harness-cli` (run/replay/record/gate-tune/sandbox-probe) | cli | v1 |

### M8 — Benchmarks

| WP | Atom | Depends | Deploy |
|---|---|---|---|
| A-H-32 | `bench-golden-replay` (byte-identical, zero re-roll) | benchmark | v1 |
| A-H-33 | `gated-task-suite` (ground truth + risky decisions, shared baselines) | dataset | v1 |
| A-H-34 | `bench-gated-decision` (Pareto vs guardrails-only + turn-boundary HITL) | benchmark | v1 |
| A-H-35 | `bench-controlled-havoc` (hover: duplicate tool call, dead sandbox, crash) | benchmark | v1 |
| A-H-36 | `bench-reporter` → Pareto plots (JSON + PNG) | lib | v1 |

### M9 — Infra

| WP | Atom | Depends | Deploy |
|---|---|---|---|
| A-H-37 | `compose.yaml` (profiles default/v2) | infra | v1 |
| A-H-38 | `Makefile` (up/down/migrate/seed/record/replay/golden/bench) | script | v1 |
| A-H-39 | `migrations` (node-pg-migrate) | script | v1 |
| A-H-40 | `seed-scripts` (loads G-02 scenarios + golden seeds) | script | v1 |
| A-H-41 | `harness-phoenix` Arize Phoenix (:6006) | svc | v2 |
| A-H-42 | `harness-otel` OpenTelemetry Collector (GenAI semconv) | svc | v2 |

## Acceptance (= SPEC success signals)

1. Golden-run replay: byte-identical over golden corpus, zero re-rolls; any harness-code mutation breaks the golden CI snapshot.
2. Gated-decision benchmark: blown-outcome rate drops vs guardrail-only baseline at equal escape rate; Pareto shown (PNG), not claimed.
3. Controlled-havoc: duplicate tool call, unresponsive sandbox, mid-run crash all recover to a repeatable state with zero double side effects.

## Runbook (after build)

```
make up        # v1 compose
make migrate && make seed
make record    # record a golden run
make replay    # byte-identical?
make golden    # CI gate
make bench     # all three benchmarks → bench/out/
```