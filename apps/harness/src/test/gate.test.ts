import { describe, expect, it } from 'vitest';
import { gate } from '@substrate/substrate';
import { GateCore, heuristicConfidenceProvider, heuristicScore, thresholdSweep, paretoFrontier, DEFAULT_GATE_OPTIONS } from '../gate/gate-core';
import { expectedGateVerdict } from '../bench/gated-decision';

describe('gate primitive (C2)', () => {
  it('three-state verdict bands', () => {
    expect(gate(0.9, 0.7, 0.3)).toBe('execute');
    expect(gate(0.7, 0.7, 0.3)).toBe('execute');
    expect(gate(0.5, 0.7, 0.3)).toBe('escalate');
    expect(gate(0.3, 0.7, 0.3)).toBe('escalate');
    expect(gate(0.29, 0.7, 0.3)).toBe('reject');
    expect(gate(0.0, 0.7, 0.3)).toBe('reject');
  });

  it('expectedGateVerdict matches contract gate', () => {
    for (const [s, e, r] of [
      [0.9, 0.7, 0.3],
      [0.6, 0.8, 0.2],
      [0.1, 0.8, 0.5],
    ] as const) {
      expect(expectedGateVerdict(s, e, r)).toBe(gate(s, e, r));
    }
  });
});

describe('heuristicConfidenceProvider', () => {
  it('rewards high schema/tool/retrieval evidence and penalizes risk', () => {
    const safe = heuristicScore({ schemaValid: 1, toolOk: 1, evidenceScore: 1, riskScore: 0, retrievalSupport: 1 });
    const risky = heuristicScore({ schemaValid: 1, toolOk: 1, evidenceScore: 1, riskScore: 1, retrievalSupport: 1 });
    expect(safe).toBeGreaterThan(risky);
    expect(safe).toBeGreaterThanOrEqual(0);
    expect(safe).toBeLessThanOrEqual(1);
  });

  it('heuristic provider explains with the features it saw', async () => {
    const p = heuristicConfidenceProvider();
    const out = await p.score({ toolName: 'echo', riskScore: 0.1 });
    expect(out.modelVersion).toBe('heuristic-v1');
    expect((out.explain['heuristic'] as Record<string, unknown>)['toolName']).toBe('echo');
  });
});

describe('GateCore', () => {
  it('decide writes an id and returns verdict band', async () => {
    let n = 0;
    const core = new GateCore(DEFAULT_GATE_OPTIONS, heuristicConfidenceProvider(), () => `d-${++n}`);
    const d1 = await core.decide('echo', { toolOk: true, schemaValid: true, evidenceScore: 0.5, riskScore: 0 });
    const d2 = await core.decide('approve', { toolOk: true, schemaValid: true, evidenceScore: 0.5, riskScore: 0.9 });
    expect(d1.decisionId).toBe('d-1');
    expect(d1.verdict).toBe('execute');
    expect(d2.verdict).toBe('escalate');
  });
});

describe('threshold sweep + pareto', () => {
  it('finds trade-offs and a non-empty frontier', () => {
    const samples = [
      { score: 0.9, outcome: true },
      { score: 0.8, outcome: true },
      { score: 0.6, outcome: false },
      { score: 0.4, outcome: false },
      { score: 0.2, outcome: false },
    ];
    const points = thresholdSweep(samples, 0.05);
    expect(points.length).toBeGreaterThan(0);
    const frontier = paretoFrontier(points);
    expect(frontier.length).toBeGreaterThan(0);
    for (const p of frontier) expect(p.blownRate).toBeGreaterThanOrEqual(0);
  });

  it('sweep never has executeThreshold below rejectThreshold', () => {
    const samples = [
      { score: 0.9, outcome: true },
      { score: 0.5, outcome: false },
    ];
    const points = thresholdSweep(samples, 0.05);
    for (const p of points) {
      expect(p.executeThreshold).toBeGreaterThan(p.rejectThreshold);
    }
  });
});

const DEFAULT_GATE_THRESHOLDS = DEFAULT_GATE_OPTIONS;