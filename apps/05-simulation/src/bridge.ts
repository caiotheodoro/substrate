import {
  type Event,
  type StoredEvent,
  StoredEventSchema,
  canonicalJson,
  idempotencyKey,
} from '@substrate/substrate';
import { createHash } from 'node:crypto';

/**
 * Bridge INTO the C1 contract: turns a sim-room event stream (Python
 * social log, M7) into validated C1 StoredEvents with the SAME canonical
 * JSON + sha-256 chain discipline as sim_shard/canonical.py, so a Python
 * room run and a TS consumer agree byte-for-byte on run + chain hash.
 */

export interface SimEvent {
  seq: number;
  kind: string;
  payload: unknown;
  ts?: string;
}

function sha256(input: string): string {
  return createHash('sha256').update(input, 'utf8').digest('hex');
}

/** Clone of the Python chain_hash: sha256(prevHash + canonicalBody). */
export function chainHash(prevHash: string, body: string): string {
  return sha256(`${prevHash}${body}`);
}

/**
 * Fold an event stream into C1 StoredEvents. `toolCallId` doubles as the
 * idempotency discriminator (runId:<toolCallId>:<attempt>).
 */
export function toStoredEvents(
  runId: string,
  events: SimEvent[],
  opts: { genesisHash?: string; toolCallId?: (seq: number) => string } = {},
): StoredEvent[] {
  const genesis = opts.genesisHash ?? '0'.repeat(64);
  const toolCallId = opts.toolCallId ?? ((seq) => `sim:${seq}`);
  const chain: StoredEvent[] = [];
  let prev = genesis;
  for (const e of events) {
    const family: Event['family'] = 'stream';
    const ts = e.ts ?? new Date().toISOString();
    const body = canonicalJson({
      family,
      kind: e.kind,
      payload: e.payload,
    });
    const stored = StoredEventSchema.parse({
      family,
      kind: e.kind,
      payload: e.payload,
      runId,
      seq: e.seq,
      idempotencyKey: idempotencyKey(runId, toolCallId(e.seq), 0),
      chainHash: chainHash(prev, body),
      ts,
    });
    prev = stored.chainHash;
    chain.push(stored);
  }
  return chain;
}

/** Integrity check of an existing stream: every chain link verifies.
 * Stream events only — the sim-room chain is a `stream` family chain. */
export function verifyStream(stream: StoredEvent[], genesisHash?: string): boolean {
  let prev = genesisHash ?? '0'.repeat(64);
  for (const ev of stream) {
    if (ev.family !== 'stream') return false;
    const body = canonicalJson({
      family: 'stream',
      kind: ev.kind,
      payload: ev.payload,
    });
    if (chainHash(prev, body) !== ev.chainHash) return false;
    prev = ev.chainHash;
  }
  return true;
}

/** Publish a sim run: smoke row that ties bridge → sim-db run ids. */
export interface SimRun {
  runId: string;
  scenarioId: string;
  method: string;
  seed: number;
  asOf: string;
  metrics: Record<string, number>;
}

export function publishSimRun(run: SimRun): { runId: string; status: 'ok' } {
  if (!run.runId || !run.scenarioId) throw new Error('runId and scenarioId are required');
  return { runId: run.runId, status: 'ok' };
}