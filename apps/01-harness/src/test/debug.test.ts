import { expect, it } from 'vitest';
import { createMemoryStores } from '../db/memory';
import { RunEngine } from '../engine/engine';
import { GateCore, heuristicConfidenceProvider } from '../gate/gate-core';
import { MockToolRegistry } from '../mock-tools/tools';

it('debug hang', async () => {
  const FIXED = '2026-01-01T00:00:00.000Z';
  let n = 0;
  const clock = { now: () => FIXED, nextId: (p: string) => `${p}-${++n}` };
  const stores = createMemoryStores({ now: () => FIXED });
  const gate = new GateCore({ executeThreshold: 0.7, rejectThreshold: 0.3 }, heuristicConfidenceProvider());
  const llm = { complete: async () => ({ content: 'echoing', toolCalls: [{ name: 'echo', args: { text: 'hello' } }] }) };
  console.log('start');
  const engine = await RunEngine.start({ stores, llm, tools: new MockToolRegistry(), gate, clock }, 'say hello');
  console.log('started', engine.id);
  const out = await engine.run(1);
  console.log('done', out.reason, out.events.length);
  expect(out.reason).toBe('maxTurns');
}, 15000);
