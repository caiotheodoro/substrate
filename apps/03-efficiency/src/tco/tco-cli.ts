import { readFileSync } from 'node:fs';
import { StepRecordSchema, type StepRecord } from '@substrate/substrate';
import { loadPriceCatalog } from './price-catalog.js';
import {
  bestLever,
  leverGridCost,
  priceRowOf,
  validateBill,
  workloadCost,
  type LeverOption,
} from './tco-model.js';
import { dataFile, isMainModule } from '../lib/paths.js';

/**
 * A-E-29 tco-cli — predict + validate against the actual bill.
 *
 *   node dist/tco/tco-cli.js predict [--workload ...] [--provider litellm] [--model llama3.3:70b]
 *   node dist/tco/tco-cli.js grid    [--workload ...]          # full lever grid
 *   node dist/tco/tco-cli.js validate --actual 12.34 [--workload ...]
 *
 * The workload is a JSONL of C4 StepRecords — the same artifact the ledger
 * ingests. The fixture `src/data/e2e-workload.jsonl` (produced by the
 * e2e-cost bench) doubles as the default workload.
 */

export function workloadFixturePath(): string {
  return dataFile('e2e-workload.jsonl');
}

export function loadWorkload(path: string): StepRecord[] {
  const text = readFileSync(path, 'utf8');
  return text
    .split('\n')
    .filter((l) => l.trim() !== '')
    .map((l) => StepRecordSchema.parse(JSON.parse(l)));
}

function parseArgs(argv: string[]): Map<string, string> {
  const args = new Map<string, string>();
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
    }
  }
  return args;
}

export async function main(argv: string[]): Promise<number> {
  const command = argv[0] ?? 'predict';
  const args = parseArgs(argv.slice(1));
  const catalog = loadPriceCatalog();
  const workloadPath = args.get('workload') ?? workloadFixturePath();
  const steps = loadWorkload(workloadPath);

  if (command === 'grid') {
    const options: LeverOption[] = [
      { provider: 'ollama', model: 'llama3.1:8b', quantization: 'q4_k_m', cache: false },
      { provider: 'ollama', model: 'llama3.1:8b', quantization: 'q4_k_m', cache: true },
      { provider: 'ollama', model: 'llama3.3:70b', quantization: 'q4_k_m', cache: true },
      { provider: 'litellm', model: 'llama3.1:8b', quantization: null, cache: false },
      { provider: 'litellm', model: 'llama3.3:70b', quantization: null, cache: true },
      { provider: 'litellm', model: 'gpt-4o', quantization: null, cache: true },
    ];
    const grid = leverGridCost(steps, options, catalog).sort(
      (a, b) => a.cost.total - b.cost.total,
    );
    process.stdout.write(
      JSON.stringify(
        grid.map((g) => ({
          ...g.option,
          totalUsd: g.cost.total,
          tokenCostUsd: g.cost.tokenCost,
          latencyCostUsd: g.cost.latencyCost,
          opsCostUsd: g.cost.opsCost,
          hardwareCostUsd: g.cost.hardwareCost,
        })),
        null,
        2,
      ) + '\n',
    );
    return 0;
  }

  const provider = args.get('provider') ?? 'litellm';
  const model = args.get('model') ?? 'llama3.3:70b';
  const option: LeverOption = {
    provider,
    model,
    quantization: args.get('quantization') ?? null,
    cache: args.get('cache') === 'true',
  };
  const predicted = workloadCost(steps, priceRowOf(catalog, option));
  const best = bestLever(leverGridCost(steps, [
    { provider: 'ollama', model: 'llama3.1:8b', quantization: 'q4_k_m', cache: true },
    { provider: 'ollama', model: 'llama3.3:70b', quantization: 'q4_k_m', cache: true },
    { provider: 'litellm', model: 'llama3.1:8b', quantization: null, cache: true },
    { provider: 'litellm', model: 'llama3.3:70b', quantization: null, cache: true },
  ], catalog));

  if (command === 'validate') {
    const actual = Number(args.get('actual'));
    if (Number.isNaN(actual)) {
      process.stderr.write('validate requires --actual <usd>\n');
      return 1;
    }
    const result = validateBill(predicted.total, actual);
    process.stdout.write(JSON.stringify({ ...result, bestLever: best?.option }, null, 2) + '\n');
    return 0;
  }

  process.stdout.write(
    JSON.stringify(
      {
        workload: workloadPath,
        option,
        predicted,
        bestLever: best?.option,
        bestLeverCostUsd: best?.cost.total,
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
