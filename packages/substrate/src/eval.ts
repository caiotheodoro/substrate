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

/**
 * Cohen's kappa: inter-rater agreement over chance, for a pair of raters
 * (e.g. an LLM judge vs a human labeler) on the same items. This is the
 * calibration gate for virtual judges — Airbnb's target is high-80s–90s.
 * Perfect agreement → 1, chance-level → 0, below chance → negative.
 */
export function cohensKappa(raterA: Array<string | number>, raterB: Array<string | number>): number {
  if (raterA.length === 0) throw new Error('empty');
  if (raterA.length !== raterB.length) throw new Error('length mismatch');
  const labels = new Set([...raterA, ...raterB]);
  if (labels.size === 0) throw new Error('empty labels');
  const n = raterA.length;
  const count = (arr: Array<string | number>): Map<string | number, number> => {
    const m = new Map<string | number, number>();
    for (const v of arr) m.set(v, (m.get(v) ?? 0) + 1);
    return m;
  };
  const aCount = count(raterA);
  const bCount = count(raterB);

  let observed = 0;
  for (let i = 0; i < n; i++) {
    if (raterA[i] === raterB[i]) observed++;
  }
  const po = observed / n;

  let expected = 0;
  for (const label of labels) {
    const pa = (aCount.get(label) ?? 0) / n;
    const pb = (bCount.get(label) ?? 0) / n;
    expected += pa * pb;
  }

  if (expected === 1) return po === 1 ? 1 : 0;
  return (po - expected) / (1 - expected);
}

/**
 * Krippendorff's alpha: inter-rater agreement for any number of raters,
 * nominal/ordinal/interval data, with missing values tolerated. The
 * recommendation when more than two annotators score the same items.
 * 1 = perfect, 0 = chance, < 0 = worse than chance.
 *
 * Nominal, pairwise-difference variant, ported exactly from the canonical
 * `krippendorff` reference implementation (0.8.1): coincidence matrix
 * normalized per unit by (pairable − 1), random coincidence matrix from
 * marginals, α = 1 − Σ(o·d)/Σ(e·d). Verified against the package's
 * documented example (nominal → 0.691358).
 *
 * `ratings` is an array of units; each unit is an array of rater values
 * (`null` = missing).
 */
export function krippendorffAlpha(
  ratings: Array<Array<string | number | null>>,
): number {
  const nUnits = ratings.length;
  if (nUnits === 0) throw new Error('empty');
  if (ratings.some((u) => u.length < 2)) throw new Error('need at least 2 raters');

  const labels = new Set<string | number>();
  for (const unit of ratings) {
    for (const v of unit) {
      if (v !== null && v !== undefined) labels.add(v);
    }
  }
  if (labels.size <= 1) throw new Error('need more than one value in the domain');
  const domain = [...labels];
  const V = domain.length;
  const idx = new Map(domain.map((v, i) => [v, i]));

  const valueCounts: number[][] = ratings.map((unit) => {
    const counts = new Array<number>(V).fill(0);
    for (const v of unit) {
      if (v !== null && v !== undefined) counts[idx.get(v)!]!++;
    }
    return counts;
  });
  if (valueCounts.every((row) => row.reduce((a, b) => a + b, 0) <= 1)) {
    throw new Error('need at least one unit with values from at least two raters');
  }

  const o = Array.from({ length: V }, () => new Array<number>(V).fill(0));
  for (const unit of valueCounts) {
    const pairable = Math.max(unit.reduce((a, b) => a + b, 0), 2);
    for (let c = 0; c < V; c++) {
      for (let k = 0; k < V; k++) {
        const diag = c === k ? unit[c]! : 0;
        o[c]![k]! += (unit[c]! * unit[k]! - diag) / (pairable - 1);
      }
    }
  }

  const nV = new Array<number>(V).fill(0);
  for (let c = 0; c < V; c++) {
    for (let k = 0; k < V; k++) nV[k]! += o[c]![k]!;
  }
  const total = nV.reduce((a, b) => a + b, 0);
  const e = Array.from({ length: V }, () => new Array<number>(V).fill(0));
  for (let c = 0; c < V; c++) {
    for (let k = 0; k < V; k++) {
      const diag = c === k ? nV[c]! : 0;
      e[c]![k]! = (nV[c]! * nV[k]! - diag) / (total - 1);
    }
  }

  let obs = 0;
  let exp = 0;
  for (let c = 0; c < V; c++) {
    for (let k = 0; k < V; k++) {
      const d = c === k ? 0 : 1;
      obs += o[c]![k]! * d;
      exp += e[c]![k]! * d;
    }
  }
  if (exp === 0) return 0;
  return 1 - obs / exp;
}