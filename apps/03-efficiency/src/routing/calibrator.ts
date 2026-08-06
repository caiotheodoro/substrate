import { readFileSync } from 'node:fs';
import type { TierThresholds } from './confidence-adapter.js';
import { dataFile, isMainModule } from '../lib/paths.js';

/**
 * A-E-17 routing-calibrator — offline threshold calibration per workload
 * (RouteLLM-style, no serving involved).
 *
 * Input: a JSONL of observed steps with {confidence, cost, outcome} —
 * outcome 1 = the step would pass 01's gate. The calibrator walks the
 * candidate threshold grid, keeps every candidate whose outcome rate
 * clears the target (equal-outcome constraint), and picks the one that
 * minimizes total cost under tiering (cheap tier below `small`,
 * mid tier below `medium`). Deterministic; runs fully offline.
 */

export interface CalibrationSample {
  confidence: number;
  cost: number;
  outcome: number;
}

export interface CalibrationResult extends TierThresholds {
  cost: number;
  outcomeRate: number;
  baselineCost: number;
  baselineOutcomeRate: number;
  costReductionPct: number;
}

const CANDIDATES = [0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95];

/** Cost of running `samples` with tiered routing at the given thresholds. */
export function tieredCost(samples: readonly CalibrationSample[], thresholds: TierThresholds): number {
  let cost = 0;
  for (const s of samples) {
    const tierMultiplier =
      s.confidence >= thresholds.small ? 0.12 : s.confidence >= thresholds.medium ? 0.4 : 1;
    cost += s.cost * tierMultiplier;
  }
  return cost;
}

export function outcomeRateOf(samples: readonly CalibrationSample[]): number {
  if (samples.length === 0) return 0;
  return samples.reduce((sum, s) => sum + s.outcome, 0) / samples.length;
}

export function calibrateThresholds(
  samples: readonly CalibrationSample[],
  opts: { targetOutcomeRate?: number } = {},
): CalibrationResult {
  const target = opts.targetOutcomeRate ?? outcomeRateOf(samples);
  const baselineCost = samples.reduce((sum, s) => sum + s.cost, 0);
  const baselineOutcomeRate = outcomeRateOf(samples);

  let best: TierThresholds | null = null;
  for (const small of CANDIDATES) {
    for (const medium of CANDIDATES) {
      if (medium >= small) continue;
      const candidate: TierThresholds = { small, medium };
      const cost = tieredCost(samples, candidate);
      const rate = outcomeRateOf(samples);
      if (rate >= target - 1e-9 && (best === null || cost < tieredCost(samples, best))) {
        best = candidate;
      }
    }
  }
  const chosen = best ?? { small: 1, medium: 1 };
  const cost = tieredCost(samples, chosen);
  return {
    ...chosen,
    cost,
    outcomeRate: outcomeRateOf(samples),
    baselineCost,
    baselineOutcomeRate,
    costReductionPct: baselineCost === 0 ? 0 : (1 - cost / baselineCost) * 100,
  };
}

export function parseCalibrationSamples(text: string): CalibrationSample[] {
  const samples: CalibrationSample[] = [];
  for (const line of text.split('\n')) {
    if (line.trim() === '') continue;
    const parsed = JSON.parse(line) as CalibrationSample;
    if (typeof parsed.confidence !== 'number' || typeof parsed.outcome !== 'number') {
      throw new Error(`invalid calibration line: ${line}`);
    }
    samples.push({ confidence: parsed.confidence, cost: parsed.cost ?? 1, outcome: parsed.outcome });
  }
  return samples;
}

export function calibratorFixturePath(): string {
  return dataFile('calibration-samples.jsonl');
}

export async function main(argv: string[]): Promise<number> {
  const file = argv[0] ?? calibratorFixturePath();
  const samples = parseCalibrationSamples(readFileSync(file, 'utf8'));
  const result = calibrateThresholds(samples);
  process.stdout.write(JSON.stringify({ file, samples: samples.length, ...result }, null, 2) + '\n');
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
