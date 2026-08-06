/**
 * The eval harness core shared by every unit's benchmark: pure scoring
 * primitives so a gate is a deployment of an eval and an eval is a gate
 * in rehearsal. Python equivalents live per-unit where the ecosystem
 * demands them (see scoringrules / uncertainty-toolbox in 02/05).
 */

/** Brier score for calibrated binary confidence. Lower is better. */
export function brierScore(confidences: number[], outcomes: number[]): number {
  if (confidences.length === 0) throw new Error('empty');
  if (confidences.length !== outcomes.length) throw new Error('length mismatch');
  let sum = 0;
  for (let i = 0; i < confidences.length; i++) {
    const d = confidences[i]! - outcomes[i]!;
    sum += d * d;
  }
  return sum / confidences.length;
}

export interface EceResult {
  ece: number;
  bins: { lower: number; upper: number; accuracy: number; confidence: number; count: number }[];
}

/** Expected Calibration Error with the standard 10 equal-width bins. */
export function expectedCalibrationError(
  confidences: number[],
  outcomes: number[],
  nBins = 10,
): EceResult {
  if (confidences.length === 0) throw new Error('empty');
  if (confidences.length !== outcomes.length) throw new Error('length mismatch');
  const bins = Array.from({ length: nBins }, (_, i) => ({
    lower: i / nBins,
    upper: (i + 1) / nBins,
    accuracy: 0,
    confidence: 0,
    count: 0,
  }));
  for (let i = 0; i < confidences.length; i++) {
    const c = Math.min(confidences[i]!, 1 - 1e-9);
    const bin = Math.min(Math.floor(c * nBins), nBins - 1);
    bins[bin]!.confidence += confidences[i]!;
    bins[bin]!.accuracy += outcomes[i]!;
    bins[bin]!.count += 1;
  }
  let ece = 0;
  for (const b of bins) {
    if (b.count === 0) continue;
    b.accuracy /= b.count;
    b.confidence /= b.count;
    if (b.count > 0) ece += (b.count / confidences.length) * Math.abs(b.accuracy - b.confidence);
  }
  return { ece, bins };
}

/** Coverage of a realized value by an ensemble's level-`level` quantile interval. */
export function coverage(realized: number[], lower: number[], upper: number[], level: number): number {
  if (realized.length !== lower.length || realized.length !== upper.length) {
    throw new Error('length mismatch');
  }
  let hit = 0;
  for (let i = 0; i < realized.length; i++) {
    if (realized[i]! >= lower[i]! && realized[i]! <= upper[i]!) hit++;
  }
  return hit / realized.length;
}

/**
 * Ranking utility (NDCG-style): which k decisions would you escalate first,
 * with `relevance` 1 = escalate-worthy decision (outcome 0 when confidence
 * was high). Used by ConfBench's escalation-utility axis.
 */
export function ndcgAtK(relevances: number[], k: number): number {
  let dcg = 0;
  let idcg = 0;
  const sorted = [...relevances].sort((a, b) => b - a);
  for (let i = 0; i < Math.min(k, relevances.length); i++) {
    const rank = i + 1;
    dcg += relevances[i]! / Math.log2(rank + 1);
    idcg += sorted[i]! / Math.log2(rank + 1);
  }
  return idcg === 0 ? 0 : dcg / idcg;
}