import { z } from 'zod';
import {
  BudgetEventSchema,
  CacheEventSchema,
  StepRecordSchema,
} from '@substrate/substrate';

/**
 * A-E-01 ledger-schema — extends the C4 contract (never forks it).
 *
 * C4 StepRecord already carries EXCLUSIVE token buckets (`inputTokens`
 * excludes `cachedInputTokens`), `cacheEvent`, `latencyMs`,
 * `promptFingerprint`, `qualitySignal`, and the `decisionId` join key.
 * This module adds the analytical extensions the ledger needs:
 * cache events with per-region fingerprints, budget gate events, and
 * cost-attributed rows (the price snapshot applied at ingest time).
 * Attribute names follow the OTel GenAI conventions C4 already aligns to;
 * OTel export itself is v2 (A-E-07).
 */

export {
  StepRecordSchema,
  BudgetEventSchema,
  CacheEventSchema,
} from '@substrate/substrate';
export type { StepRecord, BudgetEvent } from '@substrate/substrate';


export const CacheEventRecordSchema = z.object({
  decisionId: z.string(),
  stepIdx: z.number().int().nonnegative(),
  /** per-region sha-256 fingerprints (A-E-10), keyed by PromptRegion. */
  regionHashes: z.record(z.string(), z.string()),
  cacheEvent: CacheEventSchema,
  /** exclusive buckets, same discipline as StepRecord. */
  inputTokens: z.number().int().nonnegative(),
  cachedInputTokens: z.number().int().nonnegative(),
  ts: z.string(),
});

export type CacheEventRecord = z.infer<typeof CacheEventRecordSchema>;

/**
 * A ledger row with cost attribution applied: the StepRecord plus the unit
 * prices (per million tokens) it was charged at. Cost rows always carry
 * decisionId — inherited from StepRecord.
 */
export const CostRowSchema = StepRecordSchema.extend({
  costUsd: z.number().nonnegative(),
  inputCostUsd: z.number().nonnegative(),
  cachedInputCostUsd: z.number().nonnegative(),
  outputCostUsd: z.number().nonnegative(),
  priceSource: z.string(),
});

export type CostRow = z.infer<typeof CostRowSchema>;

export type CacheEventOutcome = 'miss' | 'hit' | 'write' | 'provider_inclusive';
