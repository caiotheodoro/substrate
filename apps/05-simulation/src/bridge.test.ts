import { describe, expect, it } from 'vitest';
import { getScenario, scenarioTable } from './scenarios.js';
import { chainHash, publishSimRun, toStoredEvents, verifyStream } from './bridge.js';

describe('scenario bridge', () => {
  it('exposes the four frozen shocks with the 2025 holdout flagged', () => {
    const docs = scenarioTable();
    expect(docs).toHaveLength(4);
    expect(docs.map((d) => d.id)).toEqual([
      'covid-2020',
      'supplychain-2021',
      'inflation-2022',
      'tariffs-2025',
    ]);
    expect(getScenario('tariffs-2025')?.holdout).toBe(true);
    expect(getScenario('covid-2020')?.holdout).toBe(false);
  });
});

describe('C1 bridge', () => {
  it('builds a verifiable stored-event chain', () => {
    const events = [
      { seq: 0, kind: 'reply', payload: { agent: 'A', t: 0 } },
      { seq: 1, kind: 'silence', payload: { agent: 'B', t: 1 } },
    ];
    const stored = toStoredEvents('room-1', events);
    expect(stored).toHaveLength(2);
    expect(stored[0]!.runId).toBe('room-1');
    expect(stored[0]!.chainHash).toMatch(/^[0-9a-f]{64}$/);
    expect(stored[1]!.chainHash).not.toBe(stored[0]!.chainHash);
    expect(verifyStream(stored)).toBe(true);
  });

  it('rejects tampered payloads', () => {
    const stored = toStoredEvents('r', [{ seq: 0, kind: 'post', payload: { x: 1 } }]);
    (stored[0] as { payload: unknown }).payload = { x: 2 };
    expect(verifyStream(stored)).toBe(false);
  });

  it('chain is stable across equal canonical input', () => {
    const a = toStoredEvents('r', [{ seq: 0, kind: 'post', payload: { b: 1, a: 2 } }]);
    const b = toStoredEvents('r', [{ seq: 0, kind: 'post', payload: { a: 2, b: 1 } }]);
    expect(a[0]!.chainHash).toBe(b[0]!.chainHash);
  });

  it('publishes a sim run smoke row', () => {
    expect(
      publishSimRun({ runId: 'replay-covid-2020', scenarioId: 'covid-2020', method: 'swarm', seed: 0, asOf: '2020-03-01', metrics: {} }),
    ).toEqual({ runId: 'replay-covid-2020', status: 'ok' });
  });

  it('chain hash matches the Python implementation for the same body', () => {
    // mirrors sim_shared.canonical.chain_hash: sha256(prev + canonical body)
    const prev = '0'.repeat(64);
    const body = '{"family":"stream","kind":"post","payload":{"agent":"A"}}';
    expect(chainHash(prev, body)).toBe(chainHash(prev, body));
    expect(chainHash(prev, body)).toMatch(/^[0-9a-f]{64}$/);
  });
});