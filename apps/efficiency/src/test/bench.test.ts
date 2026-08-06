import { describe, expect, it } from 'vitest';
import { loadPriceCatalog } from '../tco/price-catalog.js';
import { runE2eCostBench, runConfig, buildFixture } from '../bench/e2e-cost-bench.js';
import { runQuantHonestyBench } from '../bench/quant-honesty-bench.js';
import { runDeltaHundredTurnBench } from '../bench/delta-100th-turn-bench.js';

describe('A-E-30 e2e-cost-bench — the ≥50% claim', () => {
  it('drops cost ≥50% at equal outcomes, attributable in the ledger', () => {
    const result = runE2eCostBench();
    expect(result.outcomesEqual).toBe(true);
    expect(result.stats.baseline.outcomeRate).toBeCloseTo(result.stats.routed.outcomeRate, 10);
    expect(result.stats.baseline.gatePassRate).toBeCloseTo(result.stats.routed.gatePassRate, 10);
    for (const config of ['routed', 'cached', 'delta'] as const) {
      expect(result.costDropPct[config]).toBeGreaterThanOrEqual(50);
    }
    expect(result.costDropPct.delta).toBeGreaterThan(result.costDropPct.routed);
    expect(result.costs.delta).toBeLessThan(result.costs.cached);
    expect(result.costs.cached).toBeLessThan(result.costs.baseline);
  });

  it('every config records C4 steps with exclusive buckets and decisionId', () => {
    const fixture = buildFixture();
    for (const config of ['baseline', 'routed', 'cached', 'delta'] as const) {
      const steps = runConfig(fixture, config);
      expect(steps.length).toBeGreaterThan(0);
      for (const s of steps) {
        expect(s.decisionId).toMatch(/^e2e-d/);
        expect(s.inputTokens + s.cachedInputTokens).toBeLessThanOrEqual(2100);
        expect(s.cacheEvent).toMatch(/^(miss|hit|write)$/);
      }
    }
  });

  it('produces honest headline numbers on the shipped catalog', () => {
    const result = runE2eCostBench({ catalog: loadPriceCatalog() });
    expect(result.costs.baseline).toBeGreaterThan(result.costs.delta);
    expect(result.costDropPct.delta).toBeGreaterThan(80);
  });
});

describe('A-E-31 quant-honesty-bench — measured at the gate', () => {
  it('gate-pass and outcome rates order strictly by quant tier', () => {
    const result = runQuantHonestyBench({ nSteps: 5000, seed: 7 });
    const [q8, q4, q2] = result.tiers;
    expect(q8!.gatePassRate).toBeGreaterThan(q4!.gatePassRate);
    expect(q4!.gatePassRate).toBeGreaterThan(q2!.gatePassRate);
    expect(q8!.outcomeRate).toBeGreaterThan(q4!.outcomeRate);
    expect(q4!.outcomeRate).toBeGreaterThan(q2!.outcomeRate);
    expect(q2!.costPerCompletedTaskUsd).toBeLessThan(q8!.costPerCompletedTaskUsd);
    expect(result.honestyMeter).toBe('gate-pass');
  });

  it('is deterministic for a fixed seed', () => {
    expect(runQuantHonestyBench({ seed: 1 })).toEqual(runQuantHonestyBench({ seed: 1 }));
  });
});

describe('A-E-32 delta-100th-turn-bench — does the saving survive 100 turns', () => {
  it('deltas stay ~90% cheaper than full payloads and find a squash crossover', () => {
    const result = runDeltaHundredTurnBench({ turns: 100, seed: 99 });
    expect(result.turns).toBe(100);
    expect(result.reductionPct).toBeGreaterThan(80);
    expect(result.cumulativeDeltaBytes).toBeLessThan(result.cumulativeFullBytes);
    expect(result.squashCrossoverTurn).not.toBeNull();
    expect(result.squashCrossoverTurn!).toBeGreaterThan(1);
  });

  it('is deterministic and fast (pure in-memory)', () => {
    const start = performance.now();
    const a = runDeltaHundredTurnBench({ turns: 100 });
    const b = runDeltaHundredTurnBench({ turns: 100 });
    expect(a).toEqual(b);
    expect(performance.now() - start).toBeLessThan(5000);
  });
});
