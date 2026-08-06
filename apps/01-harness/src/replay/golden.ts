import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import type { StoredEvent } from '@substrate/substrate';
import { StoredEventSchema, canonicalJson } from '@substrate/substrate';

export interface GoldenMeta {
  runId: string;
  task: string;
  tools: string;
  clock: string;
}

export const GOLDEN_TAG = '#substrate-golden v1';

export function serializeGolden(events: StoredEvent[] | unknown[], meta?: GoldenMeta): string {
  const list = StoredEventSchema.array().parse(events);
  const header = meta
    ? `${GOLDEN_TAG} runId=${meta.runId} task=${encodeURIComponent(meta.task)} tools=${meta.tools} clock=${meta.clock} events=${list.length}`
    : `${GOLDEN_TAG} events=${list.length}`;
  const lines = list.map((e) => canonicalJson(e));
  return [header, ...lines, ''].join('\n');
}

export function parseGolden(text: string): { meta: GoldenMeta | null; events: StoredEvent[] } {
  const lines = text.split('\n').filter((l) => l.trim().length > 0);
  let meta: GoldenMeta | null = null;
  const eventLines: string[] = [];
  for (const line of lines) {
    if (line.startsWith(GOLDEN_TAG)) {
      const runId = /runId=([^ ]+)/.exec(line)?.[1] ?? '';
      const task = /task=([^ ]+)/.exec(line)?.[1] ?? '';
      const tools = /tools=([^ ]+)/.exec(line)?.[1] ?? '';
      const clock = /clock=([^ ]+)/.exec(line)?.[1] ?? '';
      meta = { runId, task: decodeURIComponent(task), tools, clock };
      continue;
    }
    eventLines.push(line);
  }
  const events = StoredEventSchema.array().parse(eventLines.map((l) => JSON.parse(l) as StoredEvent));
  return { meta, events };
}

export function loadGolden(path: string): string {
  const text = readFileSync(path, 'utf8');
  return text;
}

export function goldenDigest(text: string): string {
  return createHash('sha256').update(text).digest('hex').slice(0, 16);
}

export function digestEvents(events: StoredEvent[]): string {
  return goldenDigest(serializeGolden(events));
}

export interface GoldenLine {
  runId: string;
  event: StoredEvent;
}

export function goldenLines(events: StoredEvent[]): GoldenLine[] {
  return events.map((e) => ({ runId: e.runId, event: e }));
}

export interface RecordedCompletionLine {
  fingerprint: string;
  request: { messages: Array<{ role: string; content: string }> };
  response: { content: string; toolCalls: Array<{ name: string; args: unknown }> };
}

export interface GoldenRunFixture {
  id: string;
  goldenPath: string;
  llmPath: string;
  events: StoredEvent[];
  recordings: RecordedCompletionLine[];
  meta: GoldenMeta | null;
}

export function goldenCorpusDir(baseDir = ''): string {
  return baseDir || new URL('../../golden-corpus', import.meta.url).pathname;
}

export function loadGoldenRun(
  fixture: { id: string; goldenPath: string; llmPath: string },
  baseDir = goldenCorpusDir(),
): GoldenRunFixture {
  const goldenText = readFileSync(`${baseDir}/${fixture.goldenPath}`, 'utf8');
  const llmText = readFileSync(`${baseDir}/${fixture.llmPath}`, 'utf8');
  const parsed = parseGolden(goldenText);
  const recordings = llmText
    .split('\n')
    .filter((l) => l.trim().length > 0 && !l.trim().startsWith('#'))
    .map((l) => JSON.parse(l) as RecordedCompletionLine);
  return {
    id: fixture.id,
    goldenPath: fixture.goldenPath,
    llmPath: fixture.llmPath,
    events: parsed.events,
    recordings,
    meta: parsed.meta,
  };
}