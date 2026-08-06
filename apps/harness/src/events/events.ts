import type { Event, StoredEvent } from '@substrate/substrate';
import { EventSchema, StoredEventSchema } from '@substrate/substrate';
import { chainHashOf } from '../db/memory';
import type { Stores } from '../types';

export { canonicalJson, idempotencyKey } from '@substrate/substrate';

export async function appendEvents(store: Stores, runId: string, events: Event[]): Promise<StoredEvent[]> {
  const parsed = EventSchema.array().parse(events);
  const prev = await store.events.tail(runId);
  return store.events.append(runId, parsed, prev);
}

export async function readEvents(store: Stores, runId: string): Promise<StoredEvent[]> {
  const events = await store.events.list(runId);
  return StoredEventSchema.array().parse(events);
}

export async function runEventsTail(store: Stores, runId: string): Promise<StoredEvent | null> {
  const events = await store.events.list(runId);
  return events.at(-1) ?? null;
}

export function verifyChain(events: StoredEvent[]): boolean {
  let hash: string | null = null;
  for (const e of events) {
    const expected = chainHashOf(hash, e.runId, e.seq, e.idempotencyKey, stripMeta(e));
    if (e.chainHash !== expected) return false;
    hash = e.chainHash;
  }
  return true;
}

function stripMeta(e: StoredEvent): Event {
  const { runId: _r, seq: _s, idempotencyKey: _k, chainHash: _c, ts: _t, ...event } = e;
  return event as Event;
}
