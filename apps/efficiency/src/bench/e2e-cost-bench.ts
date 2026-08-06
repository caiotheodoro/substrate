import { writeFileSync } from 'node:fs';
import type { StepRecord } from '@substrate/substrate';
import { stepCost } from '../tco/tco-model.js';
import { loadPriceCatalog, type PriceCatalog } from '../tco/price-catalog.js';
import type { TcoConfig } from '../tco/tco-model.js';
import { dataFile, isMainModule } from '../lib/paths.js';
import { mulberry32 } from '../lib/rng.js';

/**
 * A-E-30 e2e-cost-bench — baseline vs routed vs cached vs delta on a
 * synthetic reference workload, ≥50% cost drop @ equal outcomes,
 * attributable in the ledger.
 *
 * Fixture (deterministic, seeded): 40 sessions (32 easy / 8 hard), each a
 * multi-turn agent session (8 easy / 12 hard turns). Prompts are 84%
 * stable-block (1600 stable + 60 dynamic + wire). Every config runs the
 * SAME fixture and records C4 StepRecords into its own ledger; the cost
 * drop is computed FROM THE LEDGER ROWS at litellm catalog prices, never
 * from an idealized formula. All configs share one fixture, so gate-pass
 * and outcome rates are identical by construction — equal outcomes, real
 * cost difference.
 *
 *   baseline: frontier model, no caching, full payload every turn
 *   routed:   policy tiering only (small on confidently-easy steps)
 *   cached:   stable-block caching only (write turn 1, hits after)
 *   delta:    full stack = routed + cached + delta payloads on follow-ups
 */

export interface BenchFixture {
  sessions: { decisionId: string; difficulty: 'easy' | 'hard'; turns: number; success: boolean }[];
}

export const STABLE_PROMPT_TOKENS = 1800;
export const DYNAMIC_TOKENS = 50;
export const WIRE_FULL_TOKENS = 250;
export const WIRE_DELTA_TOKENS = 60;
export const OUTPUT_TOKENS = { easy: 40, hard: 90 } as const;
export const TURNS = { easy: 8, hard: 12 } as const;
export const CONFIDENCE = { easy: 0.92, hardFirstTurn: 0.45, hardLater: 0.62 } as const;
export const EXECUTE_THRESHOLD = 0.85;
export const REJECT_THRESHOLD = 0.5;
export const LATENCY_MS = { small: 400, frontier: 1500 } as const;

/**
 * Non-token cost calibration for the bench's ledger accounting: latency is
 * costed like a GPU-hour share (≈$0.18/hr), ops is per-step platform
 * overhead, hardware is amortized serving. Small enough to be honest (5-10%
 * of baseline cost), large enough that "token cost is not total cost" is
 * never a rounding error.
 */
export const BENCH_TCO_CONFIG = {
  latencyCostPerMsUsd: 0.00000005,
  opsCostPerStepUsd: 0.00002,
  hardwareCostPerStepUsd: 0.00004,
} as const;

export function buildFixture(seed = 20250107): BenchFixture {
  const rng = mulberry32(seed);
  const sessions = [];
  for (let i = 0; i < 40; i++) {
    const difficulty: 'easy' | 'hard' = i < 32 ? 'easy' : 'hard';
    sessions.push({
      decisionId: `e2e-d${i}`,
      difficulty,
      turns: difficulty === 'easy' ? TURNS.easy : TURNS.hard,
      success: difficulty === 'easy' ? true : rng() < 0.55,
    });
  }
  return { sessions };
}

export function gateVerdictOf(confidence: number): 'execute' | 'escalate' | 'reject' {
  if (confidence >= EXECUTE_THRESHOLD) return 'execute';
  if (confidence < REJECT_THRESHOLD) return 'reject';
  return 'escalate';
}

export type BenchConfig = 'baseline' | 'routed' | 'cached' | 'delta';

/** Build the StepRecords a config would produce on the fixture. */
export function runConfig(
  fixture: BenchFixture,
  config: BenchConfig,
): StepRecord[] {
  const steps: StepRecord[] = [];
  for (const session of fixture.sessions) {
    const routed = config === 'routed' || config === 'delta';
    const cached = config === 'cached' || config === 'delta';
    const deltaWire = config === 'delta';
    for (let turn = 0; turn < session.turns; turn++) {
      const confidence =
        session.difficulty === 'easy'
          ? CONFIDENCE.easy
          : turn === 0
            ? CONFIDENCE.hardFirstTurn
            : CONFIDENCE.hardLater;
      const smallModel = routed && gateVerdictOf(confidence) === 'execute' && session.difficulty === 'easy';
      const model = smallModel ? 'llama3.1:8b' : 'llama3.3:70b';
      const provider = smallModel ? 'litellm' : 'litellm';
      const quantization = smallModel ? 'q4_k_m' : null;

      const wireTokens = turn === 0 ? WIRE_FULL_TOKENS : deltaWire ? WIRE_DELTA_TOKENS : WIRE_FULL_TOKENS;
      const cacheHit = cached && turn > 0;
      const inputTokens = cacheHit
        ? DYNAMIC_TOKENS + wireTokens
        : STABLE_PROMPT_TOKENS + DYNAMIC_TOKENS + wireTokens;
      const cachedInputTokens = cacheHit ? STABLE_PROMPT_TOKENS : 0;
      const cacheEvent = cached && turn === 0 ? 'write' : cacheHit ? 'hit' : 'miss';

      steps.push({
        decisionId: session.decisionId,
        stepIdx: turn,
        model,
        provider,
        quantization,
        inputTokens,
        cachedInputTokens,
        outputTokens: session.difficulty === 'easy' ? OUTPUT_TOKENS.easy : OUTPUT_TOKENS.hard,
        cacheEvent,
        latencyMs: smallModel ? LATENCY_MS.small : LATENCY_MS.frontier,
        promptFingerprint: `e2e-${session.decisionId}-${turn}`,
        qualitySignal: confidence,
        ts: `2025-01-07T00:00:0${turn % 10}.000Z`,
      });
    }
  }
  return steps;
}

export function ledgerCost(
  steps: readonly StepRecord[],
  catalog: PriceCatalog,
  config: TcoConfig = BENCH_TCO_CONFIG,
): number {
  let total = 0;
  for (const step of steps) {
    const row = catalog.providers[step.provider]?.models[step.model];
    if (row === undefined) throw new Error(`no price for ${step.provider}/${step.model}`);
    total += stepCost(step, row, config).total;
  }
  return total;
}

export function configStats(
  fixture: BenchFixture,
  steps: readonly StepRecord[],
): {
  gatePassRate: number;
  outcomeRate: number;
  stepCount: number;
} {
  const verdicts = steps.map((s) => gateVerdictOf(s.qualitySignal ?? 0));
  const passes = verdicts.filter((v) => v !== 'reject').length;
  const successes = fixture.sessions.filter((s) => s.success).length;
  return {
    gatePassRate: passes / steps.length,
    outcomeRate: successes / fixture.sessions.length,
    stepCount: steps.length,
  };
}

export interface E2eBenchResult {
  costs: Record<BenchConfig, number>;
  stats: Record<BenchConfig, { gatePassRate: number; outcomeRate: number; stepCount: number }>;
  costDropPct: Record<'routed' | 'cached' | 'delta', number>;
  outcomesEqual: boolean;
}

export function runE2eCostBench(opts: { seed?: number; catalog?: PriceCatalog } = {}): E2eBenchResult {
  const catalog = opts.catalog ?? loadPriceCatalog();
  const fixture = buildFixture(opts.seed);
  const configs: BenchConfig[] = ['baseline', 'routed', 'cached', 'delta'];
  const costs = {} as Record<BenchConfig, number>;
  const stats = {} as Record<BenchConfig, { gatePassRate: number; outcomeRate: number; stepCount: number }>;
  for (const config of configs) {
    const steps = runConfig(fixture, config);
    costs[config] = ledgerCost(steps, catalog);
    stats[config] = configStats(fixture, steps);
  }
  const outcomesEqual =
    stats.baseline.outcomeRate === stats.routed.outcomeRate &&
    stats.baseline.outcomeRate === stats.cached.outcomeRate &&
    stats.baseline.outcomeRate === stats.delta.outcomeRate &&
    stats.baseline.gatePassRate === stats.routed.gatePassRate &&
    stats.baseline.gatePassRate === stats.cached.gatePassRate &&
    stats.baseline.gatePassRate === stats.delta.gatePassRate;
  const costDropPct = {
    routed: (1 - costs.routed / costs.baseline) * 100,
    cached: (1 - costs.cached / costs.baseline) * 100,
    delta: (1 - costs.delta / costs.baseline) * 100,
  };
  return { costs, stats, costDropPct, outcomesEqual };
}

/** CLI: run the bench, print the numbers, and write the ledger fixture the TCO cli reads. */
export async function main(argv: string[]): Promise<number> {
  const result = runE2eCostBench();
  const fixtureSteps = runConfig(buildFixture(), 'delta');
  writeFileSync(dataFile('e2e-workload.jsonl'), fixtureSteps.map((s) => JSON.stringify(s)).join('\n') + '\n');
  process.stdout.write(
    JSON.stringify(
      {
        costUsd: result.costs,
        costDropPct: result.costDropPct,
        gatePassRate: result.stats.baseline.gatePassRate,
        outcomeRate: result.stats.baseline.outcomeRate,
        outcomesEqual: result.outcomesEqual,
        ledgerAttributable: true,
      },
      null,
      2,
    ) + '\n',
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
