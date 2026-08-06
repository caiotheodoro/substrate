import type { StepRecord } from '@substrate/substrate';
import {
  assertExclusiveBuckets,
  normalizeInclusiveToExclusive,
} from './token-accounting.js';

/**
 * A-E-05 provider-adapter — normalize LiteLLM / Ollama / Anthropic usage
 * shapes into C4 StepRecords. The gate for everything entering the ledger:
 * whatever the provider reported, buckets leave this module EXCLUSIVE.
 */

export interface NormalizedUsage {
  inputTokens: number;
  cachedInputTokens: number;
  outputTokens: number;
  cacheEvent: StepRecord['cacheEvent'];
}

export interface StepMeta {
  decisionId: string;
  stepIdx: number;
  model: string;
  provider: string;
  quantization: string | null;
  promptFingerprint: string | null;
  qualitySignal: number | null;
  ts: string;
}

/** OpenAI / LiteLLM shape: prompt_tokens is INCLUSIVE of cached tokens. */
export interface OpenAiUsage {
  prompt_tokens: number;
  completion_tokens?: number;
  prompt_tokens_details?: { cached_tokens?: number };
}

/** Anthropic shape: already exclusive; cache split explicit. */
export interface AnthropicUsage {
  input_tokens: number;
  output_tokens: number;
  cache_creation_input_tokens?: number;
  cache_read_input_tokens?: number;
}

/** Ollama native shape: no cache split at all. */
export interface OllamaUsage {
  prompt_eval_count: number;
  eval_count?: number;
  prompt_eval_duration?: number;
  load_duration?: number;
  total_duration?: number;
}

export function normalizeOpenAiUsage(usage: OpenAiUsage): NormalizedUsage {
  const cached = usage.prompt_tokens_details?.cached_tokens ?? 0;
  const { inputTokens, cachedInputTokens } = normalizeInclusiveToExclusive(
    usage.prompt_tokens,
    cached,
  );
  return {
    inputTokens,
    cachedInputTokens,
    outputTokens: usage.completion_tokens ?? 0,
    cacheEvent: cached > 0 ? 'hit' : 'miss',
  };
}

export function normalizeAnthropicUsage(usage: AnthropicUsage): NormalizedUsage {
  const read = usage.cache_read_input_tokens ?? 0;
  const written = usage.cache_creation_input_tokens ?? 0;
  return {
    inputTokens: usage.input_tokens,
    cachedInputTokens: read,
    outputTokens: usage.output_tokens,
    cacheEvent: read > 0 ? 'hit' : written > 0 ? 'write' : 'miss',
  };
}

export function normalizeOllamaUsage(usage: OllamaUsage): NormalizedUsage {
  return {
    inputTokens: usage.prompt_eval_count,
    cachedInputTokens: 0,
    outputTokens: usage.eval_count ?? 0,
    cacheEvent: 'miss',
  };
}

export function latencyFromOllama(usage: OllamaUsage): number {
  const ns = usage.total_duration ?? usage.prompt_eval_duration ?? 0;
  return ns / 1e6;
}

export type CompletionUsage =
  | { provider: 'openai' | 'litellm'; usage: OpenAiUsage }
  | { provider: 'anthropic'; usage: AnthropicUsage }
  | { provider: 'ollama'; usage: OllamaUsage };

/** Turn a provider completion into a C4 StepRecord with exclusive buckets. */
export function completionToStep(
  completion: CompletionUsage,
  meta: StepMeta,
  latencyMs: number,
): StepRecord {
  const u =
    completion.provider === 'anthropic'
      ? normalizeAnthropicUsage(completion.usage)
      : completion.provider === 'ollama'
        ? normalizeOllamaUsage(completion.usage)
        : normalizeOpenAiUsage(completion.usage);
  assertExclusiveBuckets(u);
  return {
    decisionId: meta.decisionId,
    stepIdx: meta.stepIdx,
    model: meta.model,
    provider: meta.provider,
    quantization: meta.quantization,
    inputTokens: u.inputTokens,
    cachedInputTokens: u.cachedInputTokens,
    outputTokens: u.outputTokens,
    cacheEvent: u.cacheEvent,
    latencyMs,
    promptFingerprint: meta.promptFingerprint,
    qualitySignal: meta.qualitySignal,
    ts: meta.ts,
  };
}
