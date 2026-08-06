import type { GateVerdict } from '@substrate/substrate';
import { gate } from '@substrate/substrate';

export interface GateOptions {
  executeThreshold: number;
  rejectThreshold: number;
}

export interface GateScore {
  score: number;
  explain: Record<string, unknown>;
  modelVersion: string;
}

export interface ConfidenceProvider {
  score(features: Record<string, unknown>): Promise<GateScore>;
}

export interface GateDecision {
  decisionId: string;
  score: number;
  explain: Record<string, unknown>;
  verdict: GateVerdict;
}

export class GateCore {
  constructor(
    private opts: GateOptions,
    private provider: ConfidenceProvider,
    private idGen: (prefix: string) => string = (p) => `${p}-${Math.random().toString(36).slice(2, 10)}`,
  ) {}

  async decide(action: string, features: Record<string, unknown>): Promise<GateDecision> {
    const { score, explain } = await this.provider.score(features);
    const verdict = gate(score, this.opts.executeThreshold, this.opts.rejectThreshold);
    return { decisionId: this.idGen('d'), score, explain, verdict };
  }
}

export const DEFAULT_GATE_OPTIONS: GateOptions = {
  executeThreshold: 0.7,
  rejectThreshold: 0.3,
};

export function heuristicConfidenceProvider(): ConfidenceProvider {
  return {
    async score(features) {
      const score = heuristicScore(features);
      return { score, explain: { heuristic: features }, modelVersion: 'heuristic-v1' };
    },
  };
}

export function heuristicScore(features: Record<string, unknown>): number {
  let score = 0.5;
  const num = (key: string, def: number): number => {
    const v = features[key];
    if (typeof v === 'number' && Number.isFinite(v)) return v;
    if (typeof v === 'boolean') return v ? 1 : 0;
    return def;
  };
  score += num('schemaValid', 0) * 0.15;
  score += num('toolOk', 0) * 0.15;
  score += num('evidenceScore', 0.5) * 0.2;
  score -= num('riskScore', 0) * 0.3;
  score += num('retrievalSupport', 0) * 0.15;
  if (features['prohibited'] === true) score -= 0.6;
  if (features['doubleSideEffect'] === true) score -= 0.4;
  return Math.min(1, Math.max(0, score));
}

export interface SweepPoint {
  executeThreshold: number;
  rejectThreshold: number;
  escalated: number;
  escalatedRate: number;
  blown: number;
  blownRate: number;
  escapedBlown: number;
  escapedBlownRate: number;
}

export interface SweepSample {
  score: number;
  outcome: boolean;
}

export function thresholdSweep(samples: SweepSample[], grid = 0.05): SweepPoint[] {
  const points: SweepPoint[] = [];
  for (let e = 0.55; e <= 0.95 + 1e-9; e += grid) {
    for (let r = 0.05; r <= 0.45 + 1e-9; r += grid) {
      if (r >= e) continue;
      const exec = samples.filter((s) => gate(s.score, round2(e), round2(r)) === 'execute');
      const esc = samples.filter((s) => gate(s.score, round2(e), round2(r)) === 'escalate');
      const blown = exec.filter((s) => !s.outcome).length;
      points.push({
        executeThreshold: round2(e),
        rejectThreshold: round2(r),
        escalated: esc.length,
        escalatedRate: esc.length / samples.length,
        blown: blown,
        blownRate: blown / samples.length,
        escapedBlown: blown,
        escapedBlownRate: blown / samples.length,
      });
    }
  }
  return points;
}

export function paretoFrontier(points: SweepPoint[]): SweepPoint[] {
  const sorted = [...points].sort((a, b) => a.escalatedRate - b.escalatedRate || a.blownRate - b.blownRate);
  const frontier: SweepPoint[] = [];
  let bestBlown = Infinity;
  for (const p of sorted) {
    if (p.blownRate < bestBlown) {
      bestBlown = p.blownRate;
      frontier.push(p);
    }
  }
  return frontier;
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}
