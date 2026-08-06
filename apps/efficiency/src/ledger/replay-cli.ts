import { readFileSync } from 'node:fs';
import { StepRecordSchema, type StepRecord } from '@substrate/substrate';
import { MemoryLedgerStore, createLedgerStore } from './store.js';
import type { LedgerStore } from './store.js';
import { dataFile, isMainModule } from '../lib/paths.js';

/**
 * A-E-08 ledger-replay-cli — replays a JSONL of recorded steps through the
 * ledger. One StepRecord per line (C4). The fixture in
 * `src/data/recorded-steps.jsonl` stands in for 01's recorded runs; the
 * CLI accepts any harness-produced JSONL of the same shape.
 *
 *   node dist/ledger/replay-cli.js --file src/data/recorded-steps.jsonl [--base http://localhost:8100]
 *
 * `--self` ingests into an in-memory ledger (offline); default is POST to
 * the running ledger API. Summary always includes idempotency numbers.
 */

export interface ReplaySummary {
  lines: number;
  valid: number;
  inserted: number;
  duplicateIdentical: number;
  conflicts: number;
  decisions: number;
  totalInputTokens: number;
  totalCachedInputTokens: number;
  totalOutputTokens: number;
}

export function parseRecordedSteps(text: string): StepRecord[] {
  const steps: StepRecord[] = [];
  for (const line of text.split('\n')) {
    if (line.trim() === '') continue;
    steps.push(StepRecordSchema.parse(JSON.parse(line)));
  }
  return steps;
}

export function fixturePath(): string {
  return dataFile('recorded-steps.jsonl');
}

export async function replayThroughLedger(
  steps: StepRecord[],
  store: LedgerStore,
): Promise<ReplaySummary> {
  const summary: ReplaySummary = {
    lines: steps.length,
    valid: 0,
    inserted: 0,
    duplicateIdentical: 0,
    conflicts: 0,
    decisions: new Set<string>().size,
    totalInputTokens: 0,
    totalCachedInputTokens: 0,
    totalOutputTokens: 0,
  };
  const decisions = new Set<string>();
  for (const step of steps) {
    const result = await store.insertStep(step);
    if (result === 'inserted') summary.inserted++;
    else if (result === 'duplicate-identical') summary.duplicateIdentical++;
    else summary.conflicts++;
    summary.valid++;
    decisions.add(step.decisionId);
    summary.totalInputTokens += step.inputTokens;
    summary.totalCachedInputTokens += step.cachedInputTokens;
    summary.totalOutputTokens += step.outputTokens;
  }
  summary.decisions = decisions.size;
  return summary;
}

async function ingestViaHttp(base: string, steps: StepRecord[]): Promise<ReplaySummary> {
  const summary = await replayThroughLedger(steps, new MemoryLedgerStore());
  for (const step of steps) {
    const res = await fetch(`${base}/steps`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(step),
    });
    if (!res.ok && res.status !== 409) {
      throw new Error(`ledger ingest failed: ${res.status} ${await res.text()}`);
    }
  }
  return summary;
}

export async function main(argv: string[]): Promise<number> {
  const args = new Map<string, string>();
  let file: string | undefined;
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i]!;
    if (arg.startsWith('--')) {
      const key = arg.slice(2);
      const next = argv[i + 1];
      if (next !== undefined && !next.startsWith('--')) {
        args.set(key, next);
        i++;
      } else {
        args.set(key, 'true');
      }
    } else {
      file = arg;
    }
  }
  const path = file ?? args.get('file') ?? fixturePath();
  const text = readFileSync(path, 'utf8');
  const steps = parseRecordedSteps(text);
  const base = args.get('base');
  const summary = base !== undefined && base !== 'true'
    ? await ingestViaHttp(base, steps)
    : await replayThroughLedger(steps, await createLedgerStore('memory'));
  process.stdout.write(
    JSON.stringify({ file: path, ...summary, ledger: base ?? 'memory' }, null, 2) + '\n',
  );
  return 0;
}

if (isMainModule(import.meta.url)) {
  main(process.argv.slice(2)).then(
    (code) => process.exit(code),
    (err) => {
      process.stderr.write(String(err) + '\n');
      process.exit(1);
    },
  );
}
