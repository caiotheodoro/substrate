import { mulberry32 } from '../lib/rng.js';
import { isMainModule } from '../lib/paths.js';

/**
 * A-E-31 quant-honesty-bench — quantization degradation measured AT THE
 * GATE, never as perplexity. For each GGUF quant tier: gate-pass rate
 * (fraction of steps the gate would execute) and outcome rate (fraction
 * of completed tasks that succeed), plus the per-task cost. The honest
 * tradeoff is pass/outcome vs cost — a quant tier "survives" only if its
 * gate-pass and outcome rates stay inside the workload's budget.
 *
 * Deterministic fixture: each tier has a fixed gate-pass probability and a
 * fixed success-given-pass probability; the bench simulates n steps per
 * tier with a seeded RNG. No model, no perplexity, no services.
 */

export interface QuantSpec {
  quant: string;
  gatePassProb: number;
  successGivenPass: number;
  costUsdPerStep: number;
}

export const DEFAULT_QUANT_TIERS: readonly QuantSpec[] = [
  { quant: 'q8_0', gatePassProb: 0.97, successGivenPass: 0.98, costUsdPerStep: 0.004 },
  { quant: 'q4_k_m', gatePassProb: 0.93, successGivenPass: 0.95, costUsdPerStep: 0.002 },
  { quant: 'q2_k', gatePassProb: 0.8, successGivenPass: 0.88, costUsdPerStep: 0.001 },
];

export interface QuantTierResult {
  quant: string;
  gatePassRate: number;
  outcomeRate: number;
  costUsd: number;
  costPerCompletedTaskUsd: number;
}

export interface QuantBenchResult {
  tiers: QuantTierResult[];
  honestyMeter: 'gate-pass' | 'outcome';
}

export function runQuantHonestyBench(
  opts: { tiers?: readonly QuantSpec[]; nSteps?: number; seed?: number } = {},
): QuantBenchResult {
  const tiers = opts.tiers ?? DEFAULT_QUANT_TIERS;
  const n = opts.nSteps ?? 2000;
  const rng = mulberry32(opts.seed ?? 42);
  const results: QuantTierResult[] = [];

  for (const tier of tiers) {
    let passed = 0;
    let succeeded = 0;
    for (let i = 0; i < n; i++) {
      if (rng() < tier.gatePassProb) {
        passed++;
        if (rng() < tier.successGivenPass) succeeded++;
      }
    }
    const costUsd = n * tier.costUsdPerStep;
    results.push({
      quant: tier.quant,
      gatePassRate: passed / n,
      outcomeRate: succeeded / n,
      costUsd,
      costPerCompletedTaskUsd: succeeded === 0 ? Infinity : costUsd / succeeded,
    });
  }

  return { tiers: results, honestyMeter: 'gate-pass' };
}

export function printQuantBench(result: QuantBenchResult): string {
  const lines = ['quant-honesty bench (measured at the gate)'];
  for (const tier of result.tiers) {
    lines.push(
      `  ${tier.quant.padEnd(8)} gatePass=${(tier.gatePassRate * 100).toFixed(1)}% outcome=${(tier.outcomeRate * 100).toFixed(1)}% cost=$${tier.costUsd.toFixed(2)} cost/completed=$${tier.costPerCompletedTaskUsd.toFixed(4)}`,
    );
  }
  return lines.join('\n');
}

export async function main(argv: string[]): Promise<number> {
  const nSteps = Number(argv[0] ?? 2000);
  const result = runQuantHonestyBench({ nSteps });
  process.stdout.write(printQuantBench(result) + '\n');
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
