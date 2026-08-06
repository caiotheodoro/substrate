import { describe, expect, it, beforeAll, afterAll } from 'vitest';
import type { Server } from 'node:http';
import { RunEngine, EngineClock, scriptedClock } from '../engine/engine';
import { GateCore, heuristicConfidenceProvider } from '../gate/gate-core';
import { createMemoryStores } from '../db/memory';
import { remoteBudgetGateClient } from '../ledger/budget-client';
import { MockToolRegistry } from '../mock-tools/tools';
import type { LLMProvider } from '../llm/llm';
import { MemoryRecordingStore, RecordedLLM } from '../llm/llm';
import { createBudgetGateServer, evaluateBudget } from '@substrate/efficiency';
import { createLedgerServer } from '@substrate/efficiency';
import { MemoryLedgerStore } from '@substrate/efficiency';
import { listen } from '@substrate/efficiency';

/**
 * Joint 3 e2e (C4): 01's engine ← 03's budget-gate (:8103) + ledger (:8100).
 *
 * Real servers: the ACTUAL createBudgetGateServer/createLedgerServer from
 * apps/efficiency are started in-process (MemoryLedgerStore backing),
 * and the engine's budget client talks to them over HTTP with the exact
 * C4 wire format. A tight budget forces `budget.blow` → escalation →
 * rejection; the run still ENDS CLEANLY (never a crash), and the ledger
 * holds the step + budget events keyed by decisionId.
 */

const BUDGET_PORT = 18103;
const LEDGER_PORT = 18100;

function scriptedLLM(responses: Array<{ content?: string; toolCalls?: Array<{ name: string; args: unknown }> }>): LLMProvider {
  let i = 0;
  return {
    async complete() {
      const r = responses[Math.min(i++, responses.length - 1)];
      return { content: r?.content ?? '', toolCalls: (r?.toolCalls ?? []) as never };
    },
  };
}

async function runWithBudget(
  budgetPerDecision: number,
  resolveEscalations = false,
  runSeed = '1',
): Promise<{ events: { family: string; kind?: string }[]; ended: boolean }> {
  const stores = createMemoryStores({ now: () => '2026-01-01T00:00:00.000Z' });
  const clock: EngineClock = scriptedClock([runSeed]);
  const gate = new GateCore({ executeThreshold: 0.7, rejectThreshold: 0.3 }, heuristicConfidenceProvider(), (p) => clock.nextId(p));
  const budgetGate = remoteBudgetGateClient({ gateUrl: `http://127.0.0.1:${BUDGET_PORT}`, ledgerUrl: `http://127.0.0.1:${LEDGER_PORT}` });
  const llm = scriptedLLM([
    { content: 'Running.', toolCalls: [{ name: 'echo', args: { text: 'hello' } }] },
    { content: 'Done.', toolCalls: [] },
  ]);
  const engine = await RunEngine.start(
    {
      stores,
      llm,
      tools: new MockToolRegistry(),
      gate,
      clock,
      maxTurns: 2,
      budgetGate,
      budget: { tokensPerStep: 1000, budgetPerDecision },
    },
    'say hello via echo',
  );
  let poll: ReturnType<typeof setInterval> | null = null;
  if (resolveEscalations) {
    poll = setInterval(async () => {
      const escs = await stores.escalations.list();
      for (const e of escs) {
        if (e.verdict === 'pending') await stores.escalations.decide(e.id, 'vetoed', 'test');
      }
    }, 5);
  }
  try {
    const outcome = await engine.run(2);
    return { events: outcome.events as never[], ended: true };
  } finally {
    if (poll) clearInterval(poll);
  }
}

describe('joint3 C4 — 01 engine ← 03 budget gate + ledger', () => {
  let budgetServer: Server;
  let ledgerServer: Server;
  let ledgerStore: MemoryLedgerStore;
  let budgetStore: MemoryLedgerStore;

  beforeAll(async () => {
    budgetStore = new MemoryLedgerStore();
    budgetServer = createBudgetGateServer(budgetStore);
    await listen(budgetServer, BUDGET_PORT);

    ledgerStore = new MemoryLedgerStore();
    ledgerServer = createLedgerServer(ledgerStore);
    await listen(ledgerServer, LEDGER_PORT);
  });

  afterAll(() => {
    budgetServer.close();
    ledgerServer.close();
  });

  it('generous budget: tool executes, step lands in the ledger', async () => {
    const { events } = await runWithBudget(100000);
    expect(events.some((e) => e.family === 'capture')).toBe(true);
    expect(events.some((e) => e.kind === 'budget.blow')).toBe(false);
    const steps = await ledgerStore.listSteps();
    expect(steps.length).toBeGreaterThan(0);
    expect(steps[0]!.decisionId).toBeTruthy();
    expect(steps[0]!.inputTokens).toBe(1000);
  });

  it('tight budget: blow → escalation → veto → tool rejected, clean run.end', async () => {
    const { events, ended } = await runWithBudget(100, true, '2');
    expect(events.some((e) => e.kind === 'budget.blow')).toBe(true);
    expect(events.some((e) => e.kind === 'tool.rejected')).toBe(true);
    expect(ended).toBe(true);
    const budgets = await budgetStore.listBudgetEvents();
    expect(budgets.some((b) => b.outcome === 'blow')).toBe(true);
    expect(budgets.every((b) => b.decisionId)).toBe(true);
  }, 15000);

  it('evaluateBudget is the two-sided threshold (pure)', () => {
    expect(evaluateBudget({ decisionId: 'd', stepIdx: 0, estimatedTokens: 100, budget: 200 })).toBe('pass');
    expect(evaluateBudget({ decisionId: 'd', stepIdx: 0, estimatedTokens: 250, budget: 200 })).toBe('blow');
  });
});
