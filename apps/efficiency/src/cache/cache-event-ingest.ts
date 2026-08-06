import type { StepRecord } from '@substrate/substrate';
import { normalizeInclusiveToExclusive } from '../ledger/token-accounting.js';
import type { CacheEventRecord } from '../ledger/schema.js';

/**
 * A-E-09 cache-event-ingest — normalize provider cache accounting into a
 * single CacheEvent vocabulary:
 *
 *  - Anthropic: EXCLUSIVE already (input_tokens excludes cache reads) —
 *    cache_read > 0 → hit, cache_creation > 0 → write.
 *  - OpenAI/LiteLLM: INCLUSIVE (prompt_tokens includes cached_tokens) —
 *    converted to exclusive via token-accounting before anything else.
 *
 * The C4 CacheEventSchema lives on the ledger contract; this module
 * produces the values that go into it (and into CacheEventRecord).
 */

export interface IngestedCacheEvent {
  cacheEvent: CacheEventRecord['cacheEvent'];
  inputTokens: number;
  cachedInputTokens: number;
}

export interface OpenAiCacheUsage {
  prompt_tokens: number;
  prompt_tokens_details?: { cached_tokens?: number };
}

export function ingestOpenAiCacheUsage(usage: OpenAiCacheUsage): IngestedCacheEvent {
  const cached = usage.prompt_tokens_details?.cached_tokens ?? 0;
  const { inputTokens, cachedInputTokens } = normalizeInclusiveToExclusive(
    usage.prompt_tokens,
    cached,
  );
  return {
    cacheEvent: cached > 0 ? 'hit' : 'miss',
    inputTokens,
    cachedInputTokens,
  };
}

export interface AnthropicCacheUsage {
  input_tokens: number;
  cache_creation_input_tokens?: number;
  cache_read_input_tokens?: number;
}

export function ingestAnthropicCacheUsage(usage: AnthropicCacheUsage): IngestedCacheEvent {
  const read = usage.cache_read_input_tokens ?? 0;
  const written = usage.cache_creation_input_tokens ?? 0;
  return {
    cacheEvent: read > 0 ? 'hit' : written > 0 ? 'write' : 'miss',
    inputTokens: usage.input_tokens,
    cachedInputTokens: read,
  };
}

export function cacheEventOfStep(step: StepRecord): CacheEventRecord {
  return {
    decisionId: step.decisionId,
    stepIdx: step.stepIdx,
    regionHashes: step.promptFingerprint === null ? {} : { full: step.promptFingerprint },
    cacheEvent: step.cacheEvent,
    inputTokens: step.inputTokens,
    cachedInputTokens: step.cachedInputTokens,
    ts: step.ts,
  };
}
