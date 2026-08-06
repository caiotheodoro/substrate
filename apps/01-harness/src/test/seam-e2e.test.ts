import { describe, expect, it, beforeAll, afterAll } from 'vitest';
import { spawn } from 'node:child_process';
import type { Server } from 'node:http';
import { RunEngine, EngineClock, scriptedClock } from '../engine/engine';
import { GateCore } from '../gate/gate-core';
import { resilientConfidenceProvider } from '../gate/remote-confidence';
import { createMemoryStores } from '../db/memory';
import { remoteBudgetGateClient } from '../ledger/budget-client';
import type { LLMProvider } from '../llm/llm';
import { createBudgetGateServer } from '@substrate/efficiency';
import { createLedgerServer } from '@substrate/efficiency';
import { MemoryLedgerStore } from '@substrate/efficiency';
import { listen } from '@substrate/efficiency';

/**
 * A4 — the seams, end-to-end (Airbnb Layer 4).
 *
 * One run flows through the FULL production path:
 *
 *   01 engine ──tool.call──▶ retrieve (evidence)
 *      │                          │
 *      │ gate via C5              ▼
 *      │ POST :8020/confidence ◀─ 02 trust scorer (real FastAPI, spawned)
 *      │                          │
 *      │ capture                  ▼
 *      │ POST :8204/gate ◀────── 04 grounded gate (real FastAPI, spawned)
 *      │      (C3 retrieval verdict)
 *      │                          │
 *      │ budget gate :8103 + ledger :8100  ◀─ 03 efficiency (in-process)
 *      ▼
 *   run.end — decision, budget event, step, verdict all recorded
 *
 * Component-level checks gave false assurance at the seams; this exercises
 * the combined path with the real joint servers. Tail fixtures: vetoed
 * escalation (budget blow), blocked gate (empty evidence).
 */

const TRUST_PORT = 18030;
const KNOWLEDGE_PORT = 18034;
const BUDGET_PORT = 18130;
const LEDGER_PORT = 18120;

const REPO = '/Users/caiotheodoro/Documents/personal/research';

const PYTHON_BINS: Record<string, string> = {
  '02-trust': `${REPO}/apps/02-trust/py/.venv/bin/python`,
  '04-knowledge': `${REPO}/apps/04-knowledge/py/.venv/bin/python`,
};

function spawnService(unit: string, code: string, port: number) {
  // Use the unit's venv python directly — `uv run` from a vitest worker can
  // resolve the wrong interpreter under parallel load.
  const proc = spawn(PYTHON_BINS[unit]!, ['-c', code]);
  return {
    proc,
    ready: () =>
      new Promise<void>((resolve, reject) => {
        const deadline = Date.now() + 25000;
        const probe = () => {
          if (Date.now() > deadline) return reject(new Error(`${unit} did not come up on ${port}`));
          fetch(`http://127.0.0.1:${port}/health`)
            .then((r) => (r.ok ? resolve() : setTimeout(probe, 300)))
            .catch(() => setTimeout(probe, 300));
        };
        probe();
      }),
  };
}

const TRUST_SERVER = `
import uvicorn
from trust.scorer.serve import create_app

def _deterministic_scorer():
    import numpy as np
    from trust.scorer.calibrate import SklearnIsotonic
    from trust.scorer.model import TrainedScorer, TrustScorer

    class _Booster:
        def predict(self, X, pred_contrib=False):
            if pred_contrib:
                n = X.shape[0]
                return np.zeros((n, X.shape[1] + 1))
            return np.full(X.shape[0], 0.92)

    class _Scorer:
        def __init__(self):
            self.trained = TrainedScorer(
                features=["riskScore"],
                booster=_Booster(),
                calibrator=SklearnIsotonic().fit(np.array([0.92]), np.array([1.0])),
                model_version="seam-test-v1",
            )
        def response(self, decision_id, features):
            risk = float(features.get("riskScore", 0.3))
            score = 0.95 if risk < 0.5 else 0.15
            band = "execute-band" if score >= 0.7 else ("reject-band" if score < 0.3 else "escalation-band")
            return {"score": score, "band": band, "explain": {"riskScore": risk}, "modelVersion": "seam-test-v1"}

    return _Scorer()

uvicorn.run(create_app(lambda: _deterministic_scorer()), host='127.0.0.1', port=${TRUST_PORT}, log_level='warning')
`;

const KNOWLEDGE_SERVER = `
import uvicorn
from substrate_knowledge.m6_gate.gate_api import build_gate_app
uvicorn.run(build_gate_app(), host='127.0.0.1', port=${KNOWLEDGE_PORT}, log_level='warning')
`;

function retrieveTool(knowledgeUrl: string) {
  const z = require('zod') as typeof import('zod');
  return {
    name: 'retrieve',
    description: 'Retrieve evidence passages for a claim and gate them against the knowledge base.',
    inputSchema: z.object({ claim: z.string() }),
    run: async (args: Record<string, unknown>) => {
      const claim = String(args.claim ?? '');
      const passages = ['Acme reported strong growth and rising profits.'];
      const res = await fetch(`${knowledgeUrl}/gate`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ claim, subgraph: passages }),
      });
      if (!res.ok) {
        return { ok: true, data: { verdict: 'silent', prob: 0, blocked: true, reason: `gate-http-${res.status}` } };
      }
      const body = (await res.json()) as {
        blocked?: boolean;
        reason?: string;
        verdict?: { kind: string; prob: number; citedEvidence: string | null; claim: string };
      };
      if (body.blocked || !body.verdict) {
        return { ok: true, data: { verdict: 'silent', prob: 0, blocked: body.blocked ?? false, reason: body.reason ?? null } };
      }
      return {
        ok: true,
        data: {
          verdict: body.verdict.kind,
          prob: body.verdict.prob,
          citedEvidence: body.verdict.citedEvidence,
          claim: body.verdict.claim,
        },
      };
    },
  };
}

function scriptedLLM(responses: Array<{ content?: string; toolCalls?: Array<{ name: string; args: unknown }> }>): LLMProvider {
  let i = 0;
  return {
    async complete() {
      const r = responses[Math.min(i++, responses.length - 1)];
      return { content: r?.content ?? '', toolCalls: (r?.toolCalls ?? []) as never };
    },
  };
}

interface SeamRun {
  events: { kind?: string; family?: string; payload?: Record<string, unknown> }[];
  reason: string;
}

async function runSeam(opts: {
  claim: string;
  budget: number;
  trustUrl: string;
  knowledgeUrl: string;
  budgetUrl: string;
  ledgerUrl: string;
  resolveEscalations?: boolean;
}): Promise<SeamRun> {
  const stores = createMemoryStores({ now: () => '2026-01-01T00:00:00.000Z' });
  const clock: EngineClock = scriptedClock(['1']);
  const gate = new GateCore(
    { executeThreshold: 0.7, rejectThreshold: 0.3 },
    resilientConfidenceProvider({ baseUrl: opts.trustUrl }),
    (p) => clock.nextId(p),
  );
  const budgetGate = remoteBudgetGateClient({
    gateUrl: opts.budgetUrl,
    ledgerUrl: opts.ledgerUrl,
  });
  const llm = scriptedLLM([
    { content: 'Retrieving.', toolCalls: [{ name: 'retrieve', args: { claim: opts.claim } }] },
    { content: 'Done.', toolCalls: [] },
  ]);
  const engine = await RunEngine.start(
    {
      stores,
      llm,
      tools: new (await import('../mock-tools/tools')).MockToolRegistry([retrieveTool(opts.knowledgeUrl)]),
      gate,
      clock,
      maxTurns: 2,
      budgetGate,
      budget: { tokensPerStep: 1000, budgetPerDecision: opts.budget },
    },
    'answer the claim via retrieval',
  );
  let poll: ReturnType<typeof setInterval> | null = null;
  if (opts.resolveEscalations) {
    poll = setInterval(async () => {
      const escs = await stores.escalations.list();
      for (const e of escs) {
        if (e.verdict === 'pending') await stores.escalations.decide(e.id, 'vetoed', 'seam-test');
      }
    }, 5);
  }
  try {
    const outcome = await engine.run(2);
    return { events: outcome.events as never[], reason: outcome.reason };
  } finally {
    if (poll) clearInterval(poll);
  }
}

describe('A4 seam e2e — one run through 01→02→04→03', () => {
  let trustProc: ReturnType<typeof spawn>;
  let knowledgeProc: ReturnType<typeof spawn>;
  let budgetServer: Server;
  let ledgerServer: Server;
  let budgetStore: MemoryLedgerStore;
  let ledgerStore: MemoryLedgerStore;

  beforeAll(async () => {
    const trust = spawnService('02-trust', TRUST_SERVER, TRUST_PORT);
    const knowledge = spawnService('04-knowledge', KNOWLEDGE_SERVER, KNOWLEDGE_PORT);
    trustProc = trust.proc;
    knowledgeProc = knowledge.proc;
    await Promise.all([trust.ready(), knowledge.ready()]);
    budgetStore = new MemoryLedgerStore();
    budgetServer = createBudgetGateServer(budgetStore);
    await listen(budgetServer, BUDGET_PORT);
    ledgerStore = new MemoryLedgerStore();
    ledgerServer = createLedgerServer(ledgerStore);
    await listen(ledgerServer, LEDGER_PORT);
  }, 60000);

  afterAll(() => {
    trustProc?.kill();
    knowledgeProc?.kill();
    budgetServer?.close();
    ledgerServer?.close();
  });

  it('full path: gate→verdict→budget→ledger all record for one decision', async () => {
    const run = await runSeam({
      claim: 'Acme profits rose sharply',
      budget: 100000,
      trustUrl: `http://127.0.0.1:${TRUST_PORT}`,
      knowledgeUrl: `http://127.0.0.1:${KNOWLEDGE_PORT}`,
      budgetUrl: `http://127.0.0.1:${BUDGET_PORT}`,
      ledgerUrl: `http://127.0.0.1:${LEDGER_PORT}`,
    });
    const kinds = run.events.map((e) => e.kind ?? e.family);
    // 01: tool call + capture
    expect(kinds).toContain('tool.call');
    expect(kinds).toContain('capture');
    // 02: C5 confidence via the real scorer → gate decision
    expect(kinds).toContain('gate.decision');
    // 04: retrieval verdict is inside the capture payload (real :8204 verdict)
    const capture = run.events.find((e) => e.family === 'capture') as { result?: { data?: Record<string, unknown> } };
    expect(capture.result?.data?.verdict).toBe('support');
    // 03: budget event + ledger step recorded
    const budgets = await budgetStore.listBudgetEvents();
    expect(budgets.some((b) => b.outcome === 'pass')).toBe(true);
    const steps = await ledgerStore.listSteps();
    expect(steps.length).toBeGreaterThan(0);
    expect(steps[0]!.decisionId).toBeTruthy();
    expect(steps[0]!.model).toBe('retrieve');
  }, 60000);

  it('tail: budget blow → escalation → veto → tool rejected, run ends clean', async () => {
    const run = await runSeam({
      claim: 'Acme profits rose sharply',
      budget: 100, // blow
      trustUrl: `http://127.0.0.1:${TRUST_PORT}`,
      knowledgeUrl: `http://127.0.0.1:${KNOWLEDGE_PORT}`,
      budgetUrl: `http://127.0.0.1:${BUDGET_PORT}`,
      ledgerUrl: `http://127.0.0.1:${LEDGER_PORT}`,
      resolveEscalations: true,
    });
    const kinds = run.events.map((e) => e.kind ?? e.family);
    expect(kinds).toContain('budget.blow');
    expect(kinds).toContain('escalation.created');
    expect(kinds).toContain('escalation.resolved');
    expect(kinds).toContain('tool.rejected');
    expect(run.reason).toBe('maxTurns');
    expect(kinds).toContain('run.end');
  }, 60000);

  it('tail: blocked gate (empty evidence) → silent verdict, still lands in ledger', async () => {
    const run = await runSeam({
      claim: '',
      budget: 100000,
      trustUrl: `http://127.0.0.1:${TRUST_PORT}`,
      knowledgeUrl: `http://127.0.0.1:${KNOWLEDGE_PORT}`,
      budgetUrl: `http://127.0.0.1:${BUDGET_PORT}`,
      ledgerUrl: `http://127.0.0.1:${LEDGER_PORT}`,
    });
    const capture = run.events.find((e) => e.family === 'capture') as { result?: { data?: Record<string, unknown> } };
    expect(capture.result?.data?.blocked).toBe(true);
    const steps = await ledgerStore.listSteps();
    expect(steps.length).toBeGreaterThan(0);
  }, 60000);

  it('incident regression: trust down → resilient fallback, run completes clean', async () => {
    // Seam resilience: when 02's scorer is unreachable the harness falls
    // back to the heuristic provider — a decision is made, never a crash.
    const run = await runSeam({
      claim: 'Acme profits rose sharply',
      budget: 100000,
      trustUrl: 'http://127.0.0.1:1', // dead port
      knowledgeUrl: `http://127.0.0.1:${KNOWLEDGE_PORT}`,
      budgetUrl: `http://127.0.0.1:${BUDGET_PORT}`,
      ledgerUrl: `http://127.0.0.1:${LEDGER_PORT}`,
    });
    const kinds = run.events.map((e) => e.kind ?? e.family);
    expect(kinds).toContain('gate.decision');
    expect(kinds).toContain('capture');
    expect(kinds).toContain('run.end');
  }, 60000);
});
