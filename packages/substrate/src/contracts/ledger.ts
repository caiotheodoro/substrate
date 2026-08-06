import { z } from 'zod';

/**
 * C4 — Cost ledger contract.
 *
 * Per-step attribution at the same grain as the decision log, joinable via
 * `decisionId`. Token buckets are EXCLUSIVE (Langfuse contract): `input`
 * excludes `cachedInput`; provider-inclusive counts must be converted.
 */
export const CacheEventSchema = z.enum([
  'miss',
  'hit',
  'write',
  'provider_inclusive',
]);

export const StepRecordSchema = z.object({
  decisionId: z.string(),
  stepIdx: z.number().int().nonnegative(),
  model: z.string(),
  provider: z.string(),
  quantization: z.string().nullable(),
  /** Exclusive buckets. */
  inputTokens: z.number().int().nonnegative(),
  cachedInputTokens: z.number().int().nonnegative(),
  outputTokens: z.number().int().nonnegative(),
  cacheEvent: CacheEventSchema,
  latencyMs: z.number().nonnegative(),
  promptFingerprint: z.string().nullable(),
  /** Quality signal: 02's confidence or gate verdict, when known. */
  qualitySignal: z.number().nullable(),
  ts: z.string(),
});

export type StepRecord = z.infer<typeof StepRecordSchema>;

export const BudgetEventSchema = z.object({
  decisionId: z.string(),
  stepIdx: z.number().int().nonnegative(),
  estimatedTokens: z.number().nonnegative(),
  budget: z.number().nonnegative(),
  outcome: z.enum(['pass', 'blow']),
});

export type BudgetEvent = z.infer<typeof BudgetEventSchema>;
