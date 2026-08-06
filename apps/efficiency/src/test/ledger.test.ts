import { describe, expect, it } from 'vitest';
import type { StepRecord } from '@substrate/substrate';
import {
  assertExclusiveBuckets,
  enforceExclusiveAgainstProvider,
  estimatePromptTokens,
  normalizeInclusiveToExclusive,
} from '../ledger/token-accounting.js';
import {
  completionToStep,
  latencyFromOllama,
  normalizeAnthropicUsage,
  normalizeOpenAiUsage,
  normalizeOllamaUsage,
} from '../ledger/provider-adapter.js';
import { evaluateBudget } from '../ledger/budget-gate.js';
import { createLedgerServer } from '../ledger/api.js';
import { MemoryLedgerStore } from '../ledger/store.js';
import { listen } from '../lib/http.js';
import { parseRecordedSteps, replayThroughLedger } from '../ledger/replay-cli.js';
import { readFileSync } from 'node:fs';
import { dataFile } from '../lib/paths.js';

const step = (decisionId: string, stepIdx: number, overrides: Partial<StepRecord> = {}): StepRecord => ({
  decisionId,
  stepIdx,
  model: 'llama3.1:8b',
  provider: 'ollama',
  quantization: 'q4_k_m',
  inputTokens: 100,
  cachedInputTokens: 900,
  outputTokens: 50,
  cacheEvent: 'hit',
  latencyMs: 120,
  promptFingerprint: 'fp',
  qualitySignal: 0.9,
  ts: 't',
  ...overrides,
});

describe('A-E-04 token-accounting', () => {
  it('normalizes inclusive provider counts to EXCLUSIVE buckets', () => {
    expect(normalizeInclusiveToExclusive(1000, 300)).toEqual({
      inputTokens: 700,
      cachedInputTokens: 300,
    });
    expect(normalizeInclusiveToExclusive(1000, 0)).toEqual({ inputTokens: 1000, cachedInputTokens: 0 });
  });

  it('rejects corrupt usage (cached > inclusive input)', () => {
    expect(() => normalizeInclusiveToExclusive(100, 200)).toThrow();
  });

  it('asserts the exclusive invariant on every ledger-facing record', () => {
    expect(() => assertExclusiveBuckets({ inputTokens: 5, cachedInputTokens: 2, outputTokens: 3 })).not.toThrow();
    expect(() => assertExclusiveBuckets({ inputTokens: -1, cachedInputTokens: 0, outputTokens: 0 })).toThrow();
    expect(() => assertExclusiveBuckets({ inputTokens: 1.5, cachedInputTokens: 0, outputTokens: 0 })).toThrow();
  });

  it('enforces exclusive buckets against a provider total when known', () => {
    expect(() =>
      enforceExclusiveAgainstProvider({ inputTokens: 700, cachedInputTokens: 300 }, 1000),
    ).not.toThrow();
    expect(() =>
      enforceExclusiveAgainstProvider({ inputTokens: 800, cachedInputTokens: 300 }, 1000),
    ).toThrow();
  });

  it('splits a prompt into stable (cache-eligible) and dynamic buckets', () => {
    const stableText = 'a'.repeat(100);
    const dynamicText = 'b'.repeat(50);
    const split = estimatePromptTokens(stableText, dynamicText);
    expect(split.cachedInputTokens).toBeGreaterThan(split.inputTokens);
    expect(split.total).toBe(split.inputTokens + split.cachedInputTokens);
  });
});

describe('A-E-05 provider-adapter', () => {
  it('converts OpenAI inclusive usage to exclusive buckets', () => {
    const usage = normalizeOpenAiUsage({
      prompt_tokens: 1000,
      completion_tokens: 40,
      prompt_tokens_details: { cached_tokens: 850 },
    });
    expect(usage).toEqual({
      inputTokens: 150,
      cachedInputTokens: 850,
      outputTokens: 40,
      cacheEvent: 'hit',
    });
  });

  it('keeps Anthropic exclusive usage exclusive', () => {
    const usage = normalizeAnthropicUsage({
      input_tokens: 200,
      output_tokens: 30,
      cache_creation_input_tokens: 0,
      cache_read_input_tokens: 900,
    });
    expect(usage.inputTokens).toBe(200);
    expect(usage.cachedInputTokens).toBe(900);
    expect(usage.cacheEvent).toBe('hit');
  });

  it('handles Ollama with no cache split', () => {
    const usage = normalizeOllamaUsage({ prompt_eval_count: 500, eval_count: 25 });
    expect(usage.cacheEvent).toBe('miss');
    expect(usage.cachedInputTokens).toBe(0);
  });

  it('turns a completion into a C4 StepRecord with exclusive buckets', () => {
    const record = completionToStep(
      { provider: 'litellm', usage: { prompt_tokens: 1000, completion_tokens: 30, prompt_tokens_details: { cached_tokens: 900 } } },
      { decisionId: 'd1', stepIdx: 0, model: 'm', provider: 'litellm', quantization: null, promptFingerprint: 'fp', qualitySignal: 0.8, ts: 't' },
      45,
    );
    expect(record.inputTokens).toBe(100);
    expect(record.cachedInputTokens).toBe(900);
    expect(record.outputTokens).toBe(30);
    expect(record.decisionId).toBe('d1');
    expect(record.latencyMs).toBe(45);
  });

  it('extracts latency from Ollama durations', () => {
    expect(latencyFromOllama({ prompt_eval_count: 1, total_duration: 2_500_000 })).toBe(2.5);
  });
});

describe('A-E-03 ledger-db (memory)', () => {
  it('enforces unique (decision_id, step_idx) with idempotent re-insert', async () => {
    const store = new MemoryLedgerStore();
    expect(await store.insertStep(step('d1', 0))).toBe('inserted');
    expect(await store.insertStep(step('d1', 0))).toBe('duplicate-identical');
    expect(await store.insertStep(step('d1', 0, { outputTokens: 99 }))).toBe('conflict');
    expect(await store.insertStep(step('d1', 1))).toBe('inserted');
    expect((await store.listSteps()).length).toBe(2);
  });

  it('stores budget events keyed by decision', async () => {
    const store = new MemoryLedgerStore();
    await store.insertBudgetEvent({ decisionId: 'd', stepIdx: 0, estimatedTokens: 10, budget: 5, outcome: 'blow' });
    expect(await store.listBudgetEvents()).toHaveLength(1);
  });
});

describe('A-E-02 ledger-api', () => {
  it('ingests idempotently and replays by decision_id over HTTP', async () => {
    const store = new MemoryLedgerStore();
    const server = createLedgerServer(store);
    const port = await listen(server, 0);
    const base = `http://127.0.0.1:${port}`;
    const post = (body: unknown) =>
      fetch(`${base}/steps`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
    const first = await post(step('d1', 0));
    const second = await post(step('d1', 0));
    expect(((await first.json()) as { result: string }).result).toBe('inserted');
    expect(((await second.json()) as { result: string }).result).toBe('duplicate-identical');
    const conflict = await post(step('d1', 0, { outputTokens: 7 }));
    expect(conflict.status).toBe(409);
    const replay = (await fetch(`${base}/steps?decisionId=d1`).then((r) => r.json())) as { steps: StepRecord[] };
    expect(replay.steps).toHaveLength(1);
    expect(replay.steps[0]!.inputTokens).toBe(100);
    server.close();
  });
});

describe('A-E-06 budget-gate', () => {
  it('a blow is a decision outcome, never a crash', () => {
    expect(evaluateBudget({ decisionId: 'd', stepIdx: 0, estimatedTokens: 100, budget: 200 })).toBe('pass');
    expect(evaluateBudget({ decisionId: 'd', stepIdx: 0, estimatedTokens: 300, budget: 200 })).toBe('blow');
  });
});

describe('A-E-08 ledger-replay-cli', () => {
  it('parses the recorded-steps fixture and replays it with idempotency accounting', async () => {
    const text = readFileSync(dataFile('recorded-steps.jsonl'), 'utf8');
    const steps = parseRecordedSteps(text);
    expect(steps.length).toBeGreaterThanOrEqual(12);
    expect(new Set(steps.map((s) => s.decisionId)).size).toBe(3);
    const store = new MemoryLedgerStore();
    const first = await replayThroughLedger(steps, store);
    const second = await replayThroughLedger(steps, store);
    expect(first.inserted).toBe(steps.length);
    expect(first.duplicateIdentical).toBe(0);
    expect(second.duplicateIdentical).toBe(steps.length);
    expect(first.totalInputTokens).toBeGreaterThan(0);
    expect(second.decisions).toBe(3);
  });
});
