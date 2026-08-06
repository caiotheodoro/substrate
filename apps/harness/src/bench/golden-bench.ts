import { goldenCorpusDir, loadGoldenRun } from '../replay/golden';
import { regenerateRun } from '../replay/replay';

export interface GoldenBenchResult {
  cases: Array<{ id: string; byteIdentical: boolean; rerolls: number; events: number; ms: number }>;
  allIdentical: boolean;
  zeroRerolls: boolean;
  digest: string;
}

export function goldenCorpusIndex(): Array<{ id: string; goldenPath: string; llmPath: string }> {
  return [
    { id: 'run-echo', goldenPath: 'run-echo.golden.jsonl', llmPath: 'run-echo.llm.jsonl' },
    { id: 'run-form', goldenPath: 'run-form.golden.jsonl', llmPath: 'run-form.llm.jsonl' },
    { id: 'run-gated', goldenPath: 'run-gated.golden.jsonl', llmPath: 'run-gated.llm.jsonl' },
  ];
}

export async function runGoldenReplayBench(baseDir = goldenCorpusDir()): Promise<GoldenBenchResult> {
  const cases: GoldenBenchResult['cases'] = [];
  for (const entry of goldenCorpusIndex()) {
    const fixture = loadGoldenRun(entry, baseDir);
    const start = Date.now();
    const result = await regenerateRun({ fixture });
    const ms = Date.now() - start;
    cases.push({
      id: entry.id,
      byteIdentical: result.byteIdentical,
      rerolls: result.rerolls,
      events: result.events.length,
      ms,
    } satisfies GoldenBenchResult['cases'][number]);
  }
  const digests = cases.map((c) => c.byteIdentical ? 'identical' : 'DIVERGED').join('|');
  return {
    cases,
    allIdentical: cases.every((c) => c.byteIdentical),
    zeroRerolls: cases.every((c) => c.rerolls === 0),
    digest: `golden[${digests}]`,
  };
}

export function goldenDigestOutcome(result: GoldenBenchResult): string {
  return result.digest;
}
