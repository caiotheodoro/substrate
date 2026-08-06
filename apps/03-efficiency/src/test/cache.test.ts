import { describe, expect, it } from 'vitest';
import {
  changedRegions,
  fingerprintRegions,
  fullFingerprint,
  stableBlockFingerprint,
} from '../cache/prompt-fingerprinter.js';
import { ingestAnthropicCacheUsage, ingestOpenAiCacheUsage } from '../cache/cache-event-ingest.js';
import { analyzeCacheEvents, type CacheAnalysis } from '../cache/cache-analytics.js';
import { hitRateAtStabilityDepth, simulateCache } from '../cache/cache-simulator.js';
import type { CacheEventRecord } from '../ledger/schema.js';
import type { PromptRegions } from '../cache/prompt-fingerprinter.js';

const baseRegions: PromptRegions = {
  identity: { role: 'assistant', name: 'substrate' },
  task: 'summarize the diff',
  tools: [{ name: 'git_diff', parameters: { a: 1 } }],
  schemas: { type: 'object' },
  'few-shot': ['a → b'],
  dynamic: { content: 'the actual payload', seq: 1 },
};

describe('A-E-10 prompt-fingerprinter', () => {
  it('identical regions produce identical hashes', () => {
    expect(fingerprintRegions(baseRegions)).toEqual(fingerprintRegions(baseRegions));
  });

  it('changing ONLY the dynamic region changes exactly that region hash', () => {
    const changed = { ...baseRegions, dynamic: { content: 'the actual payload', seq: 2 } };
    const before = fingerprintRegions(baseRegions);
    const after = fingerprintRegions(changed);
    expect(after.dynamic).not.toBe(before.dynamic);
    for (const region of ['identity', 'task', 'tools', 'schemas', 'few-shot'] as const) {
      expect(after[region]).toBe(before[region]);
    }
  });

  it('canonical JSON keeps hashes stable under key reordering', () => {
    const a = fingerprintRegions({ ...baseRegions, dynamic: { x: 1, y: [2, { z: 3 }] } });
    const b = fingerprintRegions({ ...baseRegions, dynamic: { y: [2, { z: 3 }], x: 1 } });
    expect(a).toEqual(b);
  });

  it('full fingerprint changes when any region changes', () => {
    expect(fullFingerprint(baseRegions)).not.toBe(
      fullFingerprint({ ...baseRegions, tools: [{ name: 'other' }] }),
    );
  });

  it('stable-block fingerprints ignore the dynamic region', () => {
    const stable = ['identity', 'task', 'tools', 'schemas', 'few-shot'] as const;
    const a = stableBlockFingerprint({ ...baseRegions, dynamic: { v: 1 } }, stable);
    const b = stableBlockFingerprint({ ...baseRegions, dynamic: { v: 2 } }, stable);
    expect(a).toBe(b);
  });

  it('changedRegions reports exactly the moved regions', () => {
    const changed = { ...baseRegions, dynamic: { other: true }, task: 'new task' };
    expect(changedRegions(baseRegions, changed).sort()).toEqual(['dynamic', 'task']);
  });
});

describe('A-E-09 cache-event-ingest', () => {
  it('OpenAI inclusive usage converts to exclusive + hit', () => {
    const result = ingestOpenAiCacheUsage({ prompt_tokens: 1200, prompt_tokens_details: { cached_tokens: 1000 } });
    expect(result).toEqual({ cacheEvent: 'hit', inputTokens: 200, cachedInputTokens: 1000 });
  });

  it('Anthropic exclusive usage is preserved and classified', () => {
    expect(ingestAnthropicCacheUsage({ input_tokens: 100, cache_creation_input_tokens: 800 }).cacheEvent).toBe('write');
    expect(ingestAnthropicCacheUsage({ input_tokens: 100, cache_read_input_tokens: 800 }).cacheEvent).toBe('hit');
    expect(ingestAnthropicCacheUsage({ input_tokens: 100 }).cacheEvent).toBe('miss');
  });
});

const event = (decisionId: string, stepIdx: number, regionHashes: Record<string, string>, cacheEvent: CacheEventRecord['cacheEvent']): CacheEventRecord => ({
  decisionId,
  stepIdx,
  regionHashes,
  cacheEvent,
  inputTokens: 100,
  cachedInputTokens: 0,
  ts: 't',
});

describe('A-E-11 cache-analytics', () => {
  const fp = (dynamic: string, stable = 'S1'): Record<string, string> => ({
    identity: 'h-identity',
    task: `h-task-${stable}`,
    tools: `h-tools-${stable}`,
    schemas: `h-schemas-${stable}`,
    'few-shot': `h-fewshot-${stable}`,
    dynamic,
  });

  it('computes hit rate by stable region', () => {
    const events = [
      event('d1', 0, fp('dyn1'), 'miss'),
      event('d1', 1, fp('dyn2'), 'hit'),
      event('d1', 2, fp('dyn3'), 'hit'),
      event('d2', 0, fp('dyn1', 'S2'), 'miss'),
    ];
    const analysis = analyzeCacheEvents(events);
    expect(analysis.total).toBe(4);
    expect(analysis.hitRate).toBe(0.5);
    const key = 'identity:h-identity|task:h-task-S1|tools:h-tools-S1|schemas:h-schemas-S1|few-shot:h-fewshot-S1';
    expect(analysis.byRegion[key]!.hits).toBe(2);
    expect(analysis.byRegion[key]!.rate).toBeCloseTo(2 / 3, 5);
  });

  it('classifies reuse-by-design vs stagnation', () => {
    const events = [
      event('d1', 0, fp('dyn1'), 'miss'),
      // dynamic moved on → healthy reuse of the stable block
      event('d1', 1, fp('dyn2'), 'hit'),
      event('d1', 2, fp('dyn3'), 'hit'),
      // same full prompt again → stagnation (prompt frozen)
      event('d1', 3, fp('dyn3'), 'hit'),
      event('d2', 0, fp('x', 'S2'), 'miss'),
    ];
    const analysis: CacheAnalysis = analyzeCacheEvents(events);
    expect(analysis.classification['reuse-by-design']).toBe(2);
    expect(analysis.classification.stagnation).toBe(1);
    expect(analysis.stagnationShare).toBeCloseTo(1 / 3, 5);
  });
});

describe('A-E-12 cache-simulator', () => {
  const prompt = (stable: string, dynamic: number): PromptRegions => ({
    identity: 'i',
    task: `t-${stable}`,
    tools: 'tl',
    schemas: 'sc',
    'few-shot': 'fs',
    dynamic: { seq: dynamic },
  });

  it('predicts hits only when the stable block was seen before', () => {
    const sequence = [
      prompt('S1', 1), // miss, writes S1
      prompt('S1', 2), // hit (stable block unchanged)
      prompt('S1', 3), // hit
      prompt('S2', 1), // miss, writes S2
      prompt('S2', 2), // hit
      prompt('S3', 1), // miss
    ];
    const result = simulateCache(sequence, { stableRegions: ['identity', 'task', 'tools', 'schemas', 'few-shot'] });
    expect(result.hits).toBe(3);
    expect(result.total).toBe(6);
    expect(result.hitRate).toBeCloseTo(0.5, 5);
  });

  it('respects a bounded cache capacity (LRU eviction)', () => {
    const sequence = [prompt('S1', 1), prompt('S2', 1), prompt('S3', 1), prompt('S1', 2)];
    const unlimited = simulateCache(sequence, { stableRegions: ['identity', 'task', 'tools', 'schemas', 'few-shot'] });
    const bounded = simulateCache(sequence, { stableRegions: ['identity', 'task', 'tools', 'schemas', 'few-shot'], capacity: 2 });
    expect(unlimited.hits).toBe(1);
    expect(bounded.hits).toBe(0);
  });

  it('hit rate is stable across depth when the stable regions are genuinely constant', () => {
    const sequence = Array.from({ length: 20 }, (_, i) => prompt('S0', i));
    expect(hitRateAtStabilityDepth(sequence, 5)).toBeCloseTo(19 / 20, 5);
    expect(hitRateAtStabilityDepth(sequence, 1)).toBeCloseTo(19 / 20, 5);
  });

  it('declaring a changing region stable collapses the hit rate (honesty check)', () => {
    const sequence = Array.from({ length: 20 }, (_, i) => prompt('S0', i));
    const degenerate = simulateCache(sequence, {
      stableRegions: ['identity', 'task', 'tools', 'schemas', 'few-shot', 'dynamic'],
    });
    expect(degenerate.hitRate).toBe(0);
  });

  it('deeper stability only helps regions that are actually stable', () => {
    const varyingTools = Array.from({ length: 20 }, (_, i) => ({
      ...prompt('S0', i),
      tools: `toolset-${i % 4}`,
    }));
    const shallow = hitRateAtStabilityDepth(varyingTools, 2);
    const deep = hitRateAtStabilityDepth(varyingTools, 5);
    expect(shallow).toBeGreaterThan(deep);
  });
});
