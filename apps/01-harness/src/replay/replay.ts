import type { StoredEvent } from '@substrate/substrate';
import { canonicalJson } from '@substrate/substrate';
import { createMemoryStores } from '../db/memory';
import { RunEngine, EngineClock, scriptedClock } from '../engine/engine';
import { fold, RunState } from '../state/fold';
import { GateCore, heuristicConfidenceProvider } from '../gate/gate-core';
import type { ChatRequest, LLMProvider } from '../llm/llm';
import { MemoryRecordingStore, RecordedLLM } from '../llm/llm';
import type { Stores, Escalation } from '../types';
import type { GoldenRunFixture } from './golden';

export const FIXED_NOW = '2026-01-01T00:00:00.000Z';

export interface ReplayResult {
  runId: string;
  events: StoredEvent[];
  byteIdentical: boolean;
  rerolls: number;
}

export function foldReplay(events: StoredEvent[]): RunState {
  return fold(events);
}

export function toolResultsByIdempotencyKey(events: StoredEvent[]): Map<string, unknown> {
  const map = new Map<string, unknown>();
  for (const e of events) {
    if (e.family === 'capture') map.set(e.idempotencyKey, e.result);
  }
  return map;
}

export function replayToolResults(events: StoredEvent[]): Map<string, unknown> {
  const map = new Map<string, unknown>();
  for (const e of events) {
    if (e.family === 'capture') map.set(e.toolCallId, e.result);
  }
  return map;
}

export function serializeEvents(events: StoredEvent[]): string {
  return events.map((e) => canonicalJson(e)).join('\n');
}

export function turnCount(events: StoredEvent[]): number {
  return events.filter((e) => e.family === 'stream' && e.kind === 'turn.start').length;
}

export interface RegenOptions {
  fixture: GoldenRunFixture;
  executeThreshold?: number;
  rejectThreshold?: number;
  turnLimit?: number;
}

export async function regenerateRun(opts: RegenOptions): Promise<ReplayResult> {
  const fixture = opts.fixture;
  const clock = buildRegenClock(fixture.events, fixture.meta?.runId ?? fixture.id);
  const stores = createMemoryStores({ now: () => FIXED_NOW });
  await seedEscalations(stores, fixture);

  const recording = new MemoryRecordingStore();
  for (const r of fixture.recordings) {
    await recording.set({ fingerprint: r.fingerprint, request: r.request as ChatRequest, response: r.response });
  }
  const llm = new RecordedLLM(recording, dummyLLM(), true);
  const gate = new GateCore(
    { executeThreshold: opts.executeThreshold ?? 0.7, rejectThreshold: opts.rejectThreshold ?? 0.3 },
    heuristicConfidenceProvider(),
    (prefix) => clock.nextId(prefix),
  );
  const resultsByToolCallId = replayToolResults(fixture.events);
  const maxTurns = opts.turnLimit ?? Math.max(turnCount(fixture.events), 1);
  const engine = await RunEngine.start(
    {
      stores,
      llm,
      tools: emptyTools(),
      gate,
      clock,
      maxTurns,
      hardCapTurns: maxTurns + 1,
      replayMode: true,
      replayResults: (toolCallId) => {
        const recorded = resultsByToolCallId.get(toolCallId);
        if (recorded === undefined) throw new Error(`replay miss: no recorded result for ${toolCallId}`);
        return Promise.resolve(recorded);
      },
    },
    fixture.meta?.task ?? '',
  );
  const outcome = await engine.run(maxTurns);
  return {
    runId: outcome.run.id,
    events: outcome.events,
    byteIdentical: serializeEvents(outcome.events) === serializeEvents(fixture.events),
    rerolls: llm.rerolls,
  };
}

export function buildRegenClock(events: StoredEvent[], runId: string): EngineClock {
  const ids = [runId, ...collectOrderedIds(events)];
  let i = 0;
  return {
    now: () => FIXED_NOW,
    nextId: (prefix) => {
      const chosen = ids[i++];
      return chosen ?? `${prefix}-${i}`;
    },
  };
}

function collectOrderedIds(events: StoredEvent[]): string[] {
  const ids: string[] = [];
  const seen = new Set<string>();
  const push = (id: string) => {
    if (typeof id !== 'string' || seen.has(id)) return;
    seen.add(id);
    ids.push(id);
  };
  for (const e of events) {
    if (e.family !== 'stream') continue;
    const p = (e as { payload?: Record<string, unknown> }).payload;
    if (!p) continue;
    if (typeof p.toolCallId === 'string') push(p.toolCallId as string);
    if (typeof p.decisionId === 'string') push(p.decisionId as string);
    if (typeof p.escalationId === 'string') push(p.escalationId as string);
  }
  return ids;
}

async function seedEscalations(stores: Stores, fixture: GoldenRunFixture): Promise<void> {
  const runId = fixture.meta?.runId ?? fixture.id;
  const escalations = new Map<string, Escalation>();
  for (const e of fixture.events) {
    if (e.family !== 'stream') continue;
    const p = e.payload as Record<string, unknown>;
    if (!p) continue;
    if (e.kind === 'escalation.created' && typeof p.escalationId === 'string' && typeof p.decisionId === 'string') {
      escalations.set(p.escalationId, {
        id: p.escalationId,
        runId,
        decisionId: p.decisionId,
        proposal: { action: String(p.name ?? ''), turnId: String(p.turn ?? 0), confidenceFeatures: {} },
        confidence: 0,
        explain: {},
        verdict: 'rejected',
        createdAt: FIXED_NOW,
        resolvedAt: null,
        decidedBy: null,
      });
    } else if (e.kind === 'escalation.resolved' && typeof p.escalationId === 'string' && p.verdict) {
      const cur = escalations.get(p.escalationId);
      if (cur) {
        escalations.set(p.escalationId, {
          ...cur,
          verdict: p.verdict as Escalation['verdict'],
          resolvedAt: FIXED_NOW,
          decidedBy: 'golden',
        });
      }
    }
  }
  for (const esc of escalations.values()) {
    await stores.escalations.insert(esc);
  }
}

export function dummyLLM(): LLMProvider {
  return {
    complete: async () => ({ content: 'replay fallback (should never be used)', toolCalls: [] }),
  };
}

function emptyTools() {
  return {
    list: () => [],
    call: async (name: string) => {
      throw new Error(`replay must not call tools (${name})`);
    },
  };
}