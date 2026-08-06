import { it } from 'vitest';
import { createMemoryStores } from '../db/memory';
import { streamEvent, narrativeEvent } from '../engine/engine';

it('probe append keys', async () => {
  const stores = createMemoryStores({ now: () => '2026-01-01T00:00:00.000Z' });
  const a = await stores.events.append('r1', [streamEvent('run.start', {})], { seq: -1, chainHash: null });
  console.error('A', a.map((e) => e.idempotencyKey));
  const b = await stores.events.append(
    'r1',
    [streamEvent('turn.start', { turn: 1 }), narrativeEvent('assistant.message', {})],
    { seq: 0, chainHash: a[0]?.chainHash ?? null },
  );
  console.error('B', b.map((e) => e.idempotencyKey));
});