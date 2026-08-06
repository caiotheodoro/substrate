import { describe, expect, it } from 'vitest';
import type { StepRecord } from '@substrate/substrate';
import { bestLever, leverGridCost, stepCost, validateBill, workloadCost, type LeverOption } from '../tco/tco-model.js';
import type { PriceCatalog, PriceRow } from '../tco/price-catalog.js';

const step = (overrides: Partial<StepRecord> = {}): StepRecord => ({
  decisionId: 'd1',
  stepIdx: 0,
  model: 'llama3.3:70b',
  provider: 'litellm',
  quantization: null,
  inputTokens: 1000,
  cachedInputTokens: 9000,
  outputTokens: 500,
  cacheEvent: 'hit',
  latencyMs: 1000,
  promptFingerprint: null,
  qualitySignal: null,
  ts: 't',
  ...overrides,
});

const catalog: PriceCatalog = {
  catalogVersion: 'test',
  providers: {
    litellm: {
      models: {
        'llama3.3:70b': { inputPerMtok: 0.9, cachedInputPerMtok: 0.09, outputPerMtok: 1.2, cacheWritePerMtok: 0.9 },
        'llama3.1:8b': { inputPerMtok: 0.08, cachedInputPerMtok: 0.008, outputPerMtok: 0.16, cacheWritePerMtok: 0.08 },
      },
    },
    ollama: {
      models: { 'llama3.1:8b': { inputPerMtok: 0, cachedInputPerMtok: 0, outputPerMtok: 0, cacheWritePerMtok: 0 } },
    },
  },
};

describe('A-E-27 tco-model — arithmetic', () => {
  it('computes token cost from exclusive buckets at per-million prices', () => {
    const row: PriceRow = catalog.providers.litellm!.models['llama3.3:70b']!;
    const cost = stepCost(step(), row, { latencyCostPerMsUsd: 0, opsCostPerStepUsd: 0, hardwareCostPerStepUsd: 0 });
    expect(cost.tokenCost).toBeCloseTo(1000 * 0.9e-6 + 9000 * 0.09e-6 + 500 * 1.2e-6, 10);
  });

  it('counts cache writes at the write rate', () => {
    const row: PriceRow = catalog.providers.litellm!.models['llama3.3:70b']!;
    const write = stepCost(step({ cacheEvent: 'write' }), row, { latencyCostPerMsUsd: 0, opsCostPerStepUsd: 0, hardwareCostPerStepUsd: 0 });
    const hit = stepCost(step({ cacheEvent: 'hit' }), row, { latencyCostPerMsUsd: 0, opsCostPerStepUsd: 0, hardwareCostPerStepUsd: 0 });
    expect(write.tokenCost).toBeGreaterThan(hit.tokenCost);
  });

  it('is honest about non-token costs', () => {
    const row: PriceRow = catalog.providers.ollama!.models['llama3.1:8b']!;
    const cost = stepCost(step({ provider: 'ollama', model: 'llama3.1:8b' }), row, {
      latencyCostPerMsUsd: 0.00002,
      opsCostPerStepUsd: 0.0001,
      hardwareCostPerStepUsd: 0.0005,
    });
    expect(cost.tokenCost).toBe(0);
    expect(cost.total).toBeCloseTo(1000 * 0.00002 + 0.0001 + 0.0005, 10);
  });

  it('workload cost aggregates across steps', () => {
    const row: PriceRow = catalog.providers.litellm!.models['llama3.3:70b']!;
    const cost = workloadCost([step({ stepIdx: 0 }), step({ stepIdx: 1 })], row, {
      latencyCostPerMsUsd: 0,
      opsCostPerStepUsd: 0.0001,
      hardwareCostPerStepUsd: 0,
    });
    expect(cost.steps).toBe(2);
    expect(cost.totalInputTokens).toBe(2000);
    expect(cost.opsCost).toBeCloseTo(0.0002, 10);
  });

  it('lever grid ranks options and finds the cheapest', () => {
    const options: LeverOption[] = [
      { provider: 'litellm', model: 'llama3.3:70b', quantization: null, cache: true },
      { provider: 'litellm', model: 'llama3.1:8b', quantization: 'q4_k_m', cache: true },
      { provider: 'ollama', model: 'llama3.1:8b', quantization: 'q4_k_m', cache: false },
    ];
    const grid = leverGridCost([step(), step({ stepIdx: 1 })], options, catalog, {
      latencyCostPerMsUsd: 0,
      opsCostPerStepUsd: 0,
      hardwareCostPerStepUsd: 0,
    });
    expect(grid).toHaveLength(3);
    expect(bestLever(grid)!.option.provider).toBe('ollama');
    const sorted = [...grid].sort((a, b) => a.cost.total - b.cost.total);
    expect(sorted[0]!.cost.total).toBeLessThan(sorted[2]!.cost.total);
  });
});

describe('A-E-29 tco validation', () => {
  it('reports margin against the actual bill', () => {
    expect(validateBill(10, 10).marginPct).toBe(0);
    expect(validateBill(11, 10).within).toBe(true);
    expect(validateBill(20, 10).within).toBe(false);
    expect(validateBill(20, 10).marginPct).toBe(100);
  });
});
