import { z } from 'zod';
import type { StoredEvent } from '@substrate/substrate';
import { createMemoryStores } from '../db/memory';
import { RunEngine } from '../engine/engine';
import { GateCore, heuristicConfidenceProvider } from '../gate/gate-core';
import { MockToolRegistry, ToolSpec } from '../mock-tools/tools';
import type { LLMProvider } from '../llm/llm';

export interface HavocCounter {
  calls(): number;
  effects(): number;
  resets(): number;
}

export interface HavocResult {
  scenario: string;
  passed: boolean;
  detail: Record<string, unknown>;
}

function gateFor(): GateCore {
  return new GateCore({ executeThreshold: 0.7, rejectThreshold: 0.3 }, heuristicConfidenceProvider());
}

function sideEffectSpec(): { counter: HavocCounter; spec: ToolSpec } {
  let calls = 0;
  let effects = 0;
  const counter: HavocCounter = {
    calls: () => calls,
    effects: () => effects,
    resets: () => 0,
  };
  const spec: ToolSpec = {
    name: 'side-effect',
    description: 'increments an out-of-band side effect counter',
    inputSchema: z.object({}),
    run: async () => {
      calls += 1;
      effects += 1;
      return { ok: true, data: { effect: effects } };
    },
  };
  return { counter, spec };
}

export async function runDuplicateToolCallHavoc(): Promise<HavocResult> {
  const { counter, spec } = sideEffectSpec();
  const stores = createMemoryStores();
  const registry = new MockToolRegistry([spec]);
  const llm: LLMProvider = {
    complete: async () => ({
      content: 'running the side effect twice in one response',
      toolCalls: [
        { name: 'side-effect', args: {} },
        { name: 'side-effect', args: {} },
      ],
    }),
  };
  const engine = await RunEngine.start({ stores, llm, tools: registry, gate: gateFor() }, 'duplicate-call');
  const out = await engine.run(1);
  const executions = counter.calls();
  const deduplicated = out.events.some((e) => e.family === 'stream' && e.kind === 'tool.deduplicated');
  const captures = out.events.filter((e) => e.family === 'capture');
  return {
    scenario: 'duplicate-tool-call',
    passed: executions === 1 && deduplicated && captures.length === 1,
    detail: { executions, deduplicated, captures: captures.length, events: out.events.length },
  };
}

export async function runDeadSandboxHavoc(): Promise<HavocResult> {
  let sandboxGeneration = 0;
  let effects = 0;
  let calls = 0;
  const tool: ToolSpec = {
    name: 'sandbox-exec',
    description: 'executes a command in a lease-bearing sandbox',
    inputSchema: z.object({}),
    run: async () => {
      calls += 1;
      const gen = sandboxGeneration;
      if (gen === 0) {
        sandboxGeneration += 1;
        return { ok: false, error: 'sandbox dead: lease expired (gen 0)' };
      }
      effects += 1;
      return { ok: true, data: { sandbox: gen, effect: effects } };
    },
  };
  const stores = createMemoryStores();
  const registry = new MockToolRegistry([tool]);
  const llm: LLMProvider = {
    complete: async (req) => {
      const markers = req.messages.filter((m) => m.role === 'assistant').length;
      if (markers === 0) {
        return { content: 'attempting sandbox exec', toolCalls: [{ name: 'sandbox-exec', args: {} }] };
      }
      return { content: 'retrying after lease renewal', toolCalls: [{ name: 'sandbox-exec', args: {} }] };
    },
  };
  const engine = await RunEngine.start({ stores, llm, tools: registry, gate: gateFor() }, 'dead-sandbox');
  const out = await engine.run(2);
  const result = out.events.filter((e) => e.family === 'capture');
  const succeeded = result.some((e) => (e as { result?: { ok?: boolean } }).result?.ok === true);
  return {
    scenario: 'dead-sandbox',
    passed: calls === 2 && effects === 1 && succeeded,
    detail: { calls, effects, succeeded, events: out.events.length },
  };
}

export async function runMidRunCrashHavoc(): Promise<HavocResult> {
  let effects = 0;
  const tool: ToolSpec = {
    name: 'side-effect',
    description: 'increments side effect counter',
    inputSchema: z.object({}),
    run: async () => {
      effects += 1;
      return { ok: true, data: { effect: effects } };
    },
  };
  const stores = createMemoryStores();
  const registry = new MockToolRegistry([tool]);
  const llm: LLMProvider = {
    complete: async (req) => {
      const turnMarker = req.messages.filter((m) => m.role === 'assistant').length;
      if (turnMarker >= 1) throw new Error('process killed mid-run');
      return { content: 'first step', toolCalls: [{ name: 'side-effect', args: {} }] };
    },
  };
  const engine = await RunEngine.start({ stores, llm, tools: registry, gate: gateFor() }, 'mid-run-crash');
  const first = await engine.run(3);
  const crashed = first.reason === 'crashed' || (first.events.some((e) => e.family === 'stream' && e.kind === 'run.end' && ((e as { payload?: { reason?: string } }).payload as { reason?: string } | undefined)?.reason === 'crashed'));
  const capturesAfterCrash = first.events.filter((e) => e.family === 'capture').length;

  const engine2 = RunEngine.fromExisting({ stores, llm, tools: registry, gate: gateFor() }, engine.id, 'mid-run-crash');
  const second = await engine2.run(2);
  const capturesAfterResume = second.events.filter((e) => e.family === 'capture').length;
  const endEvents = second.events.filter((e) => e.family === 'stream' && e.kind === 'run.end');
  const terminated = endEvents.length === 1 && ((endEvents[0] as { payload?: { reason?: string } }).payload as { reason?: string } | undefined)?.reason === 'crashed';
  return {
    scenario: 'mid-run-crash',
    passed: crashed && capturesAfterCrash === 1 && capturesAfterResume === 1 && effects === 1 && terminated,
    detail: { crashed, capturesAfterCrash, capturesAfterResume, effects, reason: first.reason },
  };
}

export async function runAllHavoc(): Promise<HavocResult[]> {
  return [await runDuplicateToolCallHavoc(), await runDeadSandboxHavoc(), await runMidRunCrashHavoc()];
}

export function summarizeEvents(events: StoredEvent[]): string {
  return events.map((e) => `${e.family}:${e.family === 'stream' ? e.kind : ''}`).join(',');
}