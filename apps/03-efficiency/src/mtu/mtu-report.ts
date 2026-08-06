import { loadTaskFamilies } from './task-families.js';
import { runMtuStudy, summarizeByFamily, type AblationResult } from './mtu-harness.js';
import { isMainModule } from '../lib/paths.js';

/**
 * A-E-26 mtu-report — "which part of your prompt pays for itself".
 * Runs the ablation study over the JSONL dataset and prints, per task
 * family, the token buckets ranked by contribution per token. Deterministic
 * and fully offline (the quality axis is the fake gate).
 */

export function formatReport(results: readonly AblationResult[]): string {
  const out: string[] = [];
  out.push('marginal-token-utility report');
  out.push(`tasks: ${countUnique(results, 'family')} families`);
  for (const report of summarizeByFamily(results)) {
    out.push('');
    out.push(`## ${report.family}`);
    for (const row of report.ranked) {
      out.push(
        `  ${row.region.padEnd(12)} ${row.difficulty.padEnd(4)} full=${row.fullQuality} ablated=${row.ablatedQuality} contrib=${row.contribution.toFixed(1)} tokens=${String(row.tokens).padStart(5)} contrib/token=${row.contributionPerToken.toFixed(5)}`,
      );
    }
  }
  return out.join('\n');
}

function countUnique(results: readonly AblationResult[], key: keyof AblationResult): number {
  return new Set(results.map((r) => String(r[key]))).size;
}

export async function main(argv: string[]): Promise<number> {
  const tasks = loadTaskFamilies();
  const results = runMtuStudy(tasks);
  const text = formatReport(results);
  process.stdout.write(text + '\n');
  const out = argv[0];
  if (out !== undefined && !out.startsWith('--')) {
    const { writeFileSync } = await import('node:fs');
    writeFileSync(out, text + '\n', 'utf8');
  }
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
