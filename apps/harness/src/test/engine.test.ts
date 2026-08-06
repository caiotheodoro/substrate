import { describe, expect, it } from 'vitest';
import { createMemoryStores } from '../db/memory';
import { RunEngine, scriptedClock, systemClock } from '../engine/engine';
import { GateCore, heuristicConfidenceProvider } from '../gate/gate-core';
import { MockToolRegistry, createMockTools } from '../mock-tools/tools';
import type { LLMProvider } from '../llm/llm';
import { fold } from '../state/fold';

const FIXED = '2026-01-01T00:00:00.000Z';

function fixedClock() {
  let n = 0;
  return {
    now: () => FIXED,
    nextId: (prefix: string) => `${prefix}-${++n}`,
  };
}

function staticLLM(content = 'done', toolCalls: Array<{ name: string; args: Record<string, unknown> }> = []): LLMProvider {
  return {
    complete: async () => ({ content, toolCalls }),
  };
}

function gate() {
  return new GateCore({ executeThreshold: 0.7, rejectThreshold: 0.3 }, heuristicConfidenceProvider());
}

describe('RunEngine', () => {
  it('bounded turn loop ends with run.end and maxTurns reason', async () => {
    const stores = createMemoryStores({ now: () => FIXED });
    const engine = await RunEngine.start(
      { stores, llm: staticLLM(), tools: new MockToolRegistry(), gate: gate(), clock: fixedClock(), maxTurns: 3 },
      'no tools needed',
    );
    const out = await engine.run(3);
    expect(out.reason).toBe('maxTurns');
    expect(out.events.filter((e) => e.family === 'stream' && e.kind === 'turn.start')).toHaveLength(3);
    expect(out.events.some((e) => e.family === 'stream' && e.kind === 'run.end')).toBe(true);
    const run = await stores.runs.get(engine.id);
    expect(run?.status).toBe('ended');
  });

  it('executes a low-risk tool call and records a capture', async () => {
    const stores = createMemoryStores({ now: () => FIXED });
    const llm = staticLLM('echoing', [{ name: 'echo', args: { text: 'hello' } }]);
    const engine = await RunEngine.start(
      { stores, llm, tools: new MockToolRegistry(), gate: gate(), clock: fixedClock() },
      'say hello',
    );
    const out = await engine.run(1);
    const captures = out.events.filter((e) => e.family === 'capture');
    expect(captures).toHaveLength(1);
    expect(captures[0]?.result).toEqual({ ok: true, data: { echoed: 'hello' } });
    const state = fold(out.events);
    expect(state.toolResults.get(captures[0]!.toolCallId)).toEqual({ ok: true, data: { echoed: 'hello' } });
  });

  it('deduplicates identical tool calls within one turn', async () => {
    const stores = createMemoryStores({ now: () => FIXED });
    const llm = staticLLM('twice', [
      { name: 'echo', args: { text: 'x' } },
      { name: 'echo', args: { text: 'x' } },
    ]);
    const engine = await RunEngine.start(
      { stores, llm, tools: new MockToolRegistry(), gate: gate(), clock: fixedClock() },
      'duplicate',
    );
    const out = await engine.run(1);
    const captures = out.events.filter((e) => e.family === 'capture');
    expect(captures).toHaveLength(1);
    expect(out.events.some((e) => e.family === 'stream' && e.kind === 'tool.deduplicated')).toBe(true);
  });

  it('rejects a tool call below the reject threshold with no capture', async () => {
    const stores = createMemoryStores({ now: () => FIXED });
    const lowScoreGate = new GateCore(
      { executeThreshold: 0.7, rejectThreshold: 0.3 },
      { score: async () => ({ score: 0.1, explain: { rule: 'prohibited' }, modelVersion: 'test' }) },
    );
    const llm = staticLLM('risky', [{ name: 'approve', args: { amount: 100000 } }]);
    const engine = await RunEngine.start(
      { stores, llm, tools: new MockToolRegistry(), gate: lowScoreGate, clock: fixedClock() },
      'approve big',
    );
    const out = await engine.run(1);
    expect(out.events.filter((e) => e.family === 'capture')).toHaveLength(0);
    expect(out.events.some((e) => e.family === 'stream' && e.kind === 'tool.rejected')).toBe(true);
    expect(out.events.some((e) => e.family === 'stream' && e.kind === 'gate.decision')).toBe(true);
  });

  it('escalates a mid-risk call and executes after approval', async () => {
    const stores = createMemoryStores({ now: () => FIXED });
    const llm = staticLLM('escalate me', [{ name: 'approve', args: { amount: 5000 } }]);
    const engine = await RunEngine.start(
      { stores, llm, tools: new MockToolRegistry(), gate: gate(), clock: fixedClock() },
      'approve 5k',
    );
    const runP = engine.run(1);
    setTimeout(async () => {
      const escs = await stores.escalations.list();
      for (const e of escs) await stores.escalations.decide(e.id, 'approved', 'test');
    }, 10);
    const out = await runP;
    expect(out.events.some((e) => e.family === 'stream' && e.kind === 'escalation.created')).toBe(true);
    expect(out.events.some((e) => e.family === 'stream' && e.kind === 'escalation.resolved' && (e as { payload?: { verdict?: string } }).payload?.verdict === 'approved')).toBe(true);
    expect(out.events.filter((e) => e.family === 'capture')).toHaveLength(1);
  });

  it('rejects the tool when an escalation is vetoed', async () => {
    const stores = createMemoryStores({ now: () => FIXED });
    const llm = staticLLM('veto me', [{ name: 'approve', args: { amount: 5000 } }]);
    const engine = await RunEngine.start(
      { stores, llm, tools: new MockToolRegistry(), gate: gate(), clock: fixedClock() },
      'approve 5k',
    );
    const runP = engine.run(1);
    setTimeout(async () => {
      const escs = await stores.escalations.list();
      for (const e of escs) await stores.escalations.decide(e.id, 'vetoed', 'test');
    }, 10);
    const out = await runP;
    expect(out.events.filter((e) => e.family === 'capture')).toHaveLength(0);
    expect(out.events.some((e) => e.family === 'stream' && e.kind === 'tool.rejected' && (e as { payload?: { reason?: string } }).payload?.reason === 'escalation-vetoed')).toBe(true);
  });

  it('caps a runaway loop at hardCapTurns', async () => {
    const stores = createMemoryStores({ now: () => FIXED });
    const engine = await RunEngine.start(
      {
        stores,
        llm: staticLLM('loop', [{ name: 'echo', args: { text: 'go' } }]),
        tools: new MockToolRegistry(),
        gate: gate(),
        clock: fixedClock(),
        maxTurns: 8,
        hardCapTurns: 6,
      },
      'loop',
    );
    const out = await engine.run(8);
    expect(out.events.filter((e) => e.family === 'stream' && e.kind === 'turn.start')).toHaveLength(6);
    expect(out.reason).toBe('hard-cap');
  });

  it('crashes cleanly when the LLM throws, preserving prior captures', async () => {
    const stores = createMemoryStores({ now: () => FIXED });
    let calls = 0;
    const llm: LLMProvider = {
      complete: async () => {
        calls += 1;
        if (calls === 1) return { content: 'first', toolCalls: [{ name: 'echo', args: { text: 'a' } }] };
        throw new Error('process killed');
      },
    };
    const engine = await RunEngine.start(
      { stores, llm, tools: new MockToolRegistry(), gate: gate(), clock: fixedClock() },
      'crash',
    );
    const first = await engine.run(3);
    expect(first.reason).toBe('crashed');
    expect(first.events.filter((e) => e.family === 'capture')).toHaveLength(1);
    const resumed = RunEngine.fromExisting(
      { stores, llm: staticLLM(), tools: new MockToolRegistry(), gate: gate(), clock: fixedClock() },
      engine.id,
      'crash',
    );
    const second = await resumed.run(1);
    expect(second.events.filter((e) => e.family === 'capture')).toHaveLength(1);
    expect(second.events.filter((e) => e.family === 'capture' && (e as { attempt?: number }).attempt === 0)).toHaveLength(1);
  });

  it('stores decisions in the decisions store', async () => {
    const stores = createMemoryStores({ now: () => FIXED });
    const engine = await RunEngine.start(
      { stores, llm: staticLLM('x', [{ name: 'echo', args: { text: 'y' } }]), tools: new MockToolRegistry(), gate: gate(), clock: fixedClock() },
      'decisions',
    );
    await engine.run(1);
    const decisions = await stores.decisions.list();
    expect(decisions.length).toBeGreaterThanOrEqual(1);
    expect(decisions[0]?.verdict).toBe('execute');
  });

  it('scriptedClock reproduces fixed ids and timestamps', () => {
    const clock = scriptedClock(['run-1', 'tc-2', 'd-3'], FIXED);
    expect(clock.now()).toBe(FIXED);
    expect(clock.nextId('run')).toBe('run-run-1');
    expect(clock.nextId('tc')).toBe('tc-tc-2');
  });
});
