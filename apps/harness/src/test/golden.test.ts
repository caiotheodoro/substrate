import { describe, expect, it, beforeAll } from 'vitest';
import { serializeGolden, digestEvents } from '../replay/golden';
import { loadGoldenRun, goldenCorpusDir, loadGolden } from '../replay/golden';
import { regenerateRun, turnCount, serializeEvents } from '../replay/replay';
import { GOLDEN_SPECS, recordCorpusRun } from '../golden-corpus/generator';
import type { StoredEvent } from '@substrate/substrate';
import type { GoldenRunFixture } from '../replay/golden';

const CORPUS = goldenCorpusDir();

const IDS = GOLDEN_SPECS.map((s) => s.id);

function entryFor(id: string) {
  return { id, goldenPath: `${id}.golden.jsonl`, llmPath: `${id}.llm.jsonl` };
}

beforeAll(async () => {
  for (const spec of GOLDEN_SPECS) {
    await recordCorpusRun(spec, CORPUS);
  }
});

describe('golden corpus', () => {
  it('records 3 golden runs with non-empty event streams and llm recordings', async () => {
    for (const id of IDS) {
      const fixture = loadGoldenRun(entryFor(id), CORPUS);
      expect(fixture.events.length).toBeGreaterThan(0);
      expect(fixture.recordings.length).toBeGreaterThan(0);
      expect(turnCount(fixture.events)).toBe(2);
      expect(digestEvents(fixture.events)).toMatch(/^[0-9a-f]{16}$/);
    }
  });

  it('replays each golden run byte-identically with zero rerolls', async () => {
    for (const id of IDS) {
      const fixture = loadGoldenRun(entryFor(id), CORPUS);
      const result = await regenerateRun({ fixture });
      expect(result.byteIdentical).toBe(true);
      expect(result.rerolls).toBe(0);
      expect(result.events.length).toBe(fixture.events.length);
    }
  });

  it('a mutated event stream diverges from the golden bytes', async () => {
    const fixture = loadGoldenRun(entryFor('run-echo'), CORPUS);
    const mutated = fixture.events.map((e): StoredEvent =>
      e.family === 'capture'
        ? { ...e, result: { ok: true, data: { echoed: 'MUTATED' } } }
        : e,
    );
    expect(serializeEvents(mutated)).not.toBe(loadGolden(`${CORPUS}/run-echo.golden.jsonl`));
    expect(digestEvents(mutated)).not.toBe(digestEvents(fixture.events));
  });

  it('a replay with a mutated golden diverges byte-identically from the golden', async () => {
    const fixture = loadGoldenRun(entryFor('run-echo'), CORPUS);
    const mutated = fixture.events.map((e, i): StoredEvent => {
      if (i === 2) {
        return { ...e, payload: { ...((e as { payload?: Record<string, unknown> }).payload ?? {}), content: 'ALTERED INPUT' } } as StoredEvent;
      }
      return e;
    });
    const result = await regenerateRun({ fixture: { ...fixture, events: mutated } });
    expect(result.byteIdentical).toBe(false);
    const copy = await regenerateRun({ fixture });
    expect(copy.byteIdentical).toBe(true);
  });

  it('replay serialization is stable and lossless', async () => {
    const fixture = loadGoldenRun(entryFor('run-form'), CORPUS);
    const result = await regenerateRun({ fixture });
    expect(serializeEvents(result.events)).toBe(serializeEvents(fixture.events));
  });
});