import { gate } from '@substrate/substrate';

export interface DecisionSample {
  score: number;
  outcome: boolean;
}

export interface Metrics {
  escapeRate: number;
  blownRate: number;
  escalationRate: number;
  executed: number;
  blown: number;
  total: number;
}

export const GATE_GRID = 0.05;

export type VerdictLike = 'execute' | 'escalate' | 'reject' | 'safe';

export function confusions(
  samples: DecisionSample[],
  decide: (score: number) => VerdictLike,
): Metrics {
  let executed = 0;
  let blown = 0;
  let escalated = 0;
  for (const s of samples) {
    const v = decide(s.score);
    if (v === 'execute') {
      executed += 1;
      if (!s.outcome) blown += 1;
    } else if (v === 'escalate') {
      escalated += 1;
    }
  }
  const total = samples.length;
  return {
    escapeRate: executed / total,
    blownRate: blown / total,
    escalationRate: escalated / total,
    executed,
    blown,
    total,
  };
}

export function gateMetrics(samples: DecisionSample[], exec: number, rej: number): Metrics {
  return confusions(samples, (score) => gate(score, exec, rej));
}

export function guardrailOnly(samples: DecisionSample[], threshold: number): Metrics {
  return confusions(samples, (score) => (score >= threshold ? 'execute' : 'reject'));
}

export function turnBoundaryHitl(samples: DecisionSample[], reviewEvery: number, execThreshold = 0.5): Metrics {
  let i = 0;
  return confusions(samples, (score) => {
    i += 1;
    if (score < execThreshold) return 'reject';
    if (i % reviewEvery === 0) return 'escalate';
    return 'execute';
  });
}

export interface BenchRow extends Metrics {
  name: string;
  params: Record<string, number>;
}

export function runGateBench(samples: DecisionSample[]): BenchRow[] {
  const rows: BenchRow[] = [];
  for (let e = 0.55; e <= 0.95 + 1e-9; e += GATE_GRID) {
    for (let r = 0.05; r <= 0.45 + 1e-9; r += GATE_GRID) {
      if (r >= e) continue;
      const m = gateMetrics(samples, round2(e), round2(r));
      rows.push({ ...m, name: 'gate-3state', params: { execute: round2(e), reject: round2(r) } });
    }
  }
  for (let t = 0.45; t <= 0.95 + 1e-9; t += GATE_GRID) {
    const m = guardrailOnly(samples, round2(t));
    rows.push({ ...m, name: 'guardrails-only', params: { threshold: round2(t) } });
  }
  for (let k = 2; k <= 12; k += 1) {
    const m = turnBoundaryHitl(samples, k);
    rows.push({ ...m, name: 'turn-boundary-hitl', params: { reviewEvery: k } });
  }
  return rows;
}

export function paretoBlownByEscape(rows: BenchRow[]): Array<{ escapeRate: number; blownRate: number; name: string }> {
  const best = new Map<number, { blownRate: number; name: string }>();
  for (const row of rows) {
    const key = Math.round(row.escapeRate * 100) / 100;
    const cur = best.get(key);
    if (!cur || row.blownRate < cur.blownRate) {
      best.set(key, { blownRate: row.blownRate, name: row.name });
    }
  }
  return [...best.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([escapeRate, v]) => ({ escapeRate, blownRate: v.blownRate, name: v.name }));
}

export interface AtEscapeResult {
  gate: Metrics;
  guardrailsOnly: Metrics;
  hitl: Metrics;
  gateWins: boolean;
  targetEscape: number;
}

export function compareAtEscape(samples: DecisionSample[], targetEscape: number, tolerance = 0.05): AtEscapeResult {
  const rows = runGateBench(samples);
  const gateRows = rows.filter((r) => r.name === 'gate-3state');
  const guardRows = rows.filter((r) => r.name === 'guardrails-only');
  const hitlRows = rows.filter((r) => r.name === 'turn-boundary-hitl');
  const gate = bestNear(gateRows, targetEscape, tolerance);
  const guardrailsOnly = bestNear(guardRows, targetEscape, tolerance);
  const hitl = bestNear(hitlRows, targetEscape, tolerance);
  return {
    gate,
    guardrailsOnly,
    hitl,
    gateWins: gate.blownRate < guardrailsOnly.blownRate,
    targetEscape,
  };
}

function bestNear(rows: BenchRow[], target: number, tol: number): BenchRow {
  const within = rows
    .filter((r) => Math.abs(r.escapeRate - target) <= tol)
    .sort((a, b) => a.blownRate - b.blownRate);
  if (within.length > 0) return within[0]!;
  return [...rows].sort(
    (a, b) =>
      Math.abs(a.escapeRate - target) - Math.abs(b.escapeRate - target) || a.blownRate - b.blownRate,
  )[0]!;
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

export function expectedGateVerdict(score: number, exec: number, rej: number): 'execute' | 'escalate' | 'reject' {
  return gate(score, exec, rej);
}