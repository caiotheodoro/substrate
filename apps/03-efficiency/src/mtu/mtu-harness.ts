
import { gate } from '@substrate/substrate';
import type { PromptRegion } from '../lib/prompt-regions.js';
import { defaultTokenizer, type Tokenizer } from '../ledger/token-accounting.js';
import { REGION_ORDER } from '../wire/instruction-blocks.js';
import type { TaskFamily, TaskRecord } from './task-families.js';

/**
 * A-E-24 mtu-harness — marginal-token-utility: ablates prompt regions per
 * task family and measures the quality axis WITH A DETERMINISTIC FAKE GATE
 * (02's gate contract, same two-threshold semantics — offline, no model).
 *
 * For every family × difficulty × region: run the fake gate on the full
 * prompt and on the prompt minus that region. The quality drop is the
 * region's marginal utility; tokens are the region's token cost; the
 * report ranks regions by utility per token — "which part of your prompt
 * pays for itself".
 *
 * The fixture is calibrated so hard tasks NEED their critical regions
 * (ablating them drops the verdict out of execute) while easy tasks
 * execute regardless — the honest finding that marginal utility is
 * concentrated in hard, information-bearing contexts.
 */

export type Quality = 0 | 0.5 | 1;

export interface AblationResult {
  family: TaskFamily;
  difficulty: 'easy' | 'hard';
  region: PromptRegion;
  fullQuality: Quality;
  ablatedQuality: Quality;
  contribution: number;
  tokens: number;
  contributionPerToken: number;
}

/** Per-family region contribution matrix (deterministic fixture). */
const CONTRIBUTIONS: Record<TaskFamily, Partial<Record<PromptRegion, number>>> = {
  classification: { 'few-shot': 0.28, task: 0.05, dynamic: 0.07 },
  extraction: { schemas: 0.22, task: 0.06, 'few-shot': 0.08, dynamic: 0.03 },
  'code-gen': { task: 0.25, 'few-shot': 0.12, dynamic: 0.08, tools: 0.05 },
  'ui-gen': { schemas: 0.2, task: 0.08, tools: 0.08, 'few-shot': 0.06 },
  'retrieval-answer': { dynamic: 0.3, tools: 0.06, task: 0.06 },
};

const BASE_BY_DIFFICULTY = { easy: 0.92, hard: 0.5 } as const;
const EXECUTE_THRESHOLD = 0.85;
const REJECT_THRESHOLD = 0.55;

export function fakeGateConfidence(
  family: TaskFamily,
  difficulty: 'easy' | 'hard',
  presentRegions: readonly PromptRegion[],
): number {
  const base = BASE_BY_DIFFICULTY[difficulty];
  const contributions = CONTRIBUTIONS[family];
  let confidence = base;
  for (const region of presentRegions) {
    confidence += contributions[region] ?? 0;
  }
  return Math.min(1, Math.max(0, confidence));
}

export function qualityOf(confidence: number): Quality {
  const verdict = gate(confidence, EXECUTE_THRESHOLD, REJECT_THRESHOLD);
  return verdict === 'execute' ? 1 : verdict === 'reject' ? 0 : 0.5;
}

export function runMtuStudy(
  tasks: readonly TaskRecord[],
  tokenizer: Tokenizer = defaultTokenizer,
): AblationResult[] {
  const results: AblationResult[] = [];
  for (const task of tasks) {
    const fullConfidence = fakeGateConfidence(task.family, task.difficulty, REGION_ORDER);
    const fullQuality = qualityOf(fullConfidence);
    for (const region of REGION_ORDER) {
      const ablated = REGION_ORDER.filter((r) => r !== region);
      const ablatedQuality = qualityOf(
        fakeGateConfidence(task.family, task.difficulty, ablated),
      );
      const tokens = tokenizer.countTokens(task.regions[region] ?? '');
      results.push({
        family: task.family,
        difficulty: task.difficulty,
        region,
        fullQuality: fullQuality,
        ablatedQuality: ablatedQuality,
        contribution: fullQuality - ablatedQuality,
        tokens,
        contributionPerToken: tokens === 0 ? 0 : (fullQuality - ablatedQuality) / tokens,
      });
    }
  }
  return results;
}

export interface FamilyReport {
  family: TaskFamily;
  ranked: AblationResult[];
}

export function familyRanking(
  results: readonly AblationResult[],
  family: TaskFamily,
  difficulty?: 'easy' | 'hard',
): AblationResult[] {
  const rows = results.filter(
    (r) => r.family === family && (difficulty === undefined || r.difficulty === difficulty),
  );
  return rows.sort(
    (a, b) =>
      b.contributionPerToken - a.contributionPerToken ||
      b.contribution - a.contribution,
  );
}

export function summarizeByFamily(
  results: readonly AblationResult[],
): FamilyReport[] {
  return TASK_FAMILY_LIST.map((family) => ({
    family,
    ranked: familyRanking(results, family),
  }));
}

const TASK_FAMILY_LIST = [
  'classification',
  'extraction',
  'code-gen',
  'ui-gen',
  'retrieval-answer',
] as const;
