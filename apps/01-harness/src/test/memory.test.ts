import { describe, expect, it } from 'vitest';
import { createMemoryStores, chainHashOf, sha256 } from '../db/memory';
import type { Event, StoredEvent } from '@substrate/substrate';

const NOW = () => '2026-01-01T00:00:00.000Z';

describe('memory stores', () => {
  it('appends events with monotonic seq and chained hashes', async () => {
    const stores = createMemoryStores({ now: NOW });
    const e1: Event = { family: 'stream', kind: 'turn.start', payload: { turn: 1 } };
    const e2: Event = { family: 'narrative', kind: 'assistant.message', payload: { content: 'hi' } };
    await stores.events.append('r1', [e1, e2], { seq: -1, chainHash: null });
    const list = await stores.events.list('r1');
    expect(list).toHaveLength(2);
    expect(list[0]?.seq).toBe(0);
    expect(list[1]?.seq).toBe(1);
    expect(list[0]?.chainHash).not.toBeNull();
    expect(list[1]?.chainHash).not.toBe(list[0]?.chainHash);
    const tail = await stores.events.tail('r1');
    expect(tail.seq).toBe(1);
  });

  it('concurrent duplicate appends of the same event are idempotent', async () => {
    const stores = createMemoryStores({ now: NOW });
    const evt: Event = { family: 'capture', toolCallId: 'tc-1', result: { ok: true, data: { k: 1 } }, attempt: 0, ts: NOW() };
    const prev = { seq: -1, chainHash: null };
    const a = await stores.events.append('r1', [evt], prev);
    const b = await stores.events.append('r1', [evt], prev);
    const list = await stores.events.list('r1');
    expect(list).toHaveLength(1);
    expect(a).toHaveLength(1);
    expect(b).toHaveLength(0);
  });

  it('detects chain tampering via hash mismatch', async () => {
    const stores = createMemoryStores({ now: NOW });
    const evt: Event = { family: 'stream', kind: 'tool.call', payload: { toolCallId: 't1' } };
    await stores.events.append('r1', [evt], { seq: -1, chainHash: null });
    const list = await stores.events.list('r1');
    const tampered: StoredEvent = { ...list[0]!, payload: { toolCallId: 'tampered' } } as StoredEvent;
    const recomputed = chainHashOf(null, 'r1', 0, tampered.idempotencyKey, { family: 'stream', kind: 'tool.call', payload: { toolCallId: 'tampered' } });
    expect(recomputed).not.toBe(list[0]?.chainHash);
  });

  it('runs, decisions, pending actions, escalations and thresholds round-trip', async () => {
    const stores = createMemoryStores({ now: NOW });
    await stores.runs.create({ id: 'r1', task: 't', status: 'running', reason: null, maxTurns: 3, startedAt: NOW(), endedAt: null, seq: -1 });
    await stores.decisions.insert({ decisionId: 'd1', turnId: '1', action: 'echo:d1', confidenceFeatures: { riskScore: 0.1 }, verdict: 'execute', outcome: null, confirmedAt: null });
    await stores.pendingActions.insert({ id: 'pa1', runId: 'r1', turnId: '1', kind: 'question', prompt: 'q?', schema: {}, answer: null, status: 'pending', createdAt: NOW(), resolvedAt: null, resolvedBy: null });
    await stores.escalations.insert({ id: 'e1', runId: 'r1', decisionId: 'd1', proposal: { action: 'echo', turnId: '1', confidenceFeatures: {} }, confidence: 0.4, explain: {}, verdict: 'pending', createdAt: NOW(), resolvedAt: null, decidedBy: null });
    await stores.sandboxLeases.upsert({ id: 's1', containerId: 'c1', image: 'alpine:3.20', leaseMs: 1000, expiresAt: NOW(), updatedAt: NOW(), status: 'alive' });
    await stores.thresholds.set('default', { executeThreshold: 0.7, rejectThreshold: 0.3 });
    await stores.costLedger.insert({
      decisionId: 'd1',
      stepIdx: 0,
      model: 'test',
      provider: 'memory',
      quantization: null,
      inputTokens: 10,
      cachedInputTokens: 0,
      outputTokens: 5,
      cacheEvent: 'miss',
      latencyMs: 1,
      promptFingerprint: null,
      qualitySignal: null,
      ts: NOW(),
    } as never);
    expect(await stores.runs.get('r1')).toMatchObject({ status: 'running' });
    expect((await stores.decisions.list()).map((d) => d.decisionId)).toContain('d1');
    expect((await stores.pendingActions.list('r1')).map((a) => a.id)).toContain('pa1');
    expect((await stores.escalations.list()).map((e) => e.id)).toContain('e1');
    expect((await stores.sandboxLeases.list()).map((s) => s.id)).toContain('s1');
    expect((await stores.thresholds.get('default'))?.executeThreshold).toBe(0.7);
    expect((await stores.costLedger.list())).toHaveLength(1);
  });

  it('emit notifies listeners with stored events', async () => {
    const stores = createMemoryStores({ now: NOW });
    const seen: string[] = [];
    const off = stores.emit.on((e) => seen.push(e.runId));
    const evt: Event = { family: 'stream', kind: 'run.start', payload: {} };
    await stores.events.append('r1', [evt], { seq: -1, chainHash: null });
    expect(seen).toEqual(['r1']);
    off();
    await stores.events.append('r2', [evt], { seq: -1, chainHash: null });
    expect(seen).toEqual(['r1']);
  });

  it('sha256 is hex deterministic', () => {
    expect(sha256('x')).toMatch(/^[0-9a-f]{64}$/);
    expect(sha256('x')).toBe(sha256('x'));
  });
});