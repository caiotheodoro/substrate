"""Scoring primitives shared across ConfBench, scorer-train, r1/r2.

Mirrors ``packages/substrate/src/eval.ts`` (brier, ece, coverage, ndcg). The
``metrics`` module (`trust.confbench.metrics`) adds the ConfBench axes on top:
reliability diagrams, NDCG-escalation, shift delta — backed by netcal /
uncertainty-toolbox when present, with a pure-numpy fallback so tests never
require optional imports.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def brier_score(confidences: list[float], outcomes: list[int | float]) -> float:
    """Mean squared error between calibrated confidence and binary outcome."""
    c = np.asarray(confidences, dtype=float)
    y = np.asarray(outcomes, dtype=float)
    if c.ndim != 1 or y.ndim != 1:
        raise ValueError("1-D arrays required")
    if len(c) == 0:
        raise ValueError("empty")
    if len(c) != len(y):
        raise ValueError("length mismatch")
    return float(np.mean((c - y) ** 2))


@dataclass
class BinData:
    bin_lower: float
    bin_upper: float
    confidence: float
    accuracy: float
    count: int


def expected_calibration_error(
    confidences: list[float], outcomes: list[int | float], n_bins: int = 10
) -> tuple[float, list[BinData]]:
    """Expected calibration error, standard equal-width adaptive bins.

    bins with no samples are reported with count 0 and excluded from ECE.
    """
    c = np.asarray(confidences, dtype=float)
    y = np.asarray(outcomes, dtype=float)
    if len(c) == 0:
        raise ValueError("empty")
    if len(c) != len(y):
        raise ValueError("length mismatch")
    n = len(c)
    bins: list[BinData] = []
    for i in range(n_bins):
        lo, hi = i / n_bins, (i + 1) / n_bins
        sel = (c >= lo) & (c < hi) if hi < 1.0 else (c >= lo) & (c <= hi)
        count = int(sel.sum())
        if count == 0:
            bins.append(BinData(lo, hi, 0.0, 0.0, 0))
            continue
        acc = float(y[sel].mean())
        conf = float(c[sel].mean())
        bins.append(BinData(lo, hi, conf, acc, count))
    used = [b for b in bins if b.count > 0]
    ece = sum((b.count / n) * abs(b.accuracy - b.confidence) for b in used)
    return float(ece), bins


def reliability_coverage(realized: list[float], lower: list[float], upper: list[float], level: float) -> float:
    """Fraction of realized values captured by per-sample interval [lower, upper]."""
    if not (len(realized) == len(lower) == len(upper)):
        raise ValueError("length mismatch")
    hit = sum(1 for r, lo, hi in zip(realized, lower, upper) if lo <= r <= hi)
    return hit / len(realized)


def ndcg_at_k(scores_or_relevance: list[float], k: int, order: list[int] | None = None) -> float:
    """NDCG at k. For escalation utility, pass ``relevance`` in the order you'd
    escalate and ``order`` = the ordering the system produces (defaults to the
    list order). Relevance 1 = escalate-worthy."""
    rel = np.asarray(scores_or_relevance, dtype=float)
    if len(rel) == 0:
        return 0.0
    if order is None:
        order = list(range(len(rel)))
    if len(order) < len(rel):
        raise ValueError("order shorter than relevance")
    k = min(k, len(rel))
    dcg = sum(rel[order[i]] / np.log2(i + 2) for i in range(k))
    top = -np.sort(-rel)[:k]
    idcg = sum(top[i] / np.log2(i + 2) for i in range(k))
    return float(dcg / idcg) if idcg > 0 else 0.0


def ndcg_escalation(confidence: list[float], worth: list[int | float], k: int | None = None) -> float:
    """Which *k* actions would you escalate first?

    Rank by (confidence, worth): the best intervention target is a high
    confidence decision whose outcome was bad (worth=1) in order of descending
    confidence. NDCG over the worth sequence sorted by confidence desc.
    """
    if len(confidence) != len(worth):
        raise ValueError("length mismatch")
    order = sorted(range(len(confidence)), key=lambda i: -confidence[i])
    return ndcg_at_k(list(worth), k or len(worth), order)


@dataclass
class CalibrationReport:
    brier: float
    ece: float
    bins: list[BinData]
    reliab_shape: list[float]


def big_report(confidences: list[float], outcomes: list[int | float], n_bins: int = 10) -> CalibrationReport:
    """Brier + ECE + per-bin reliability diagram data in one call."""
    brier = brier_score(confidences, outcomes)
    ece, bins = expected_calibration_error(confidences, outcomes, n_bins)
    shape = [b.accuracy - b.confidence for b in bins if b.count > 0]
    return CalibrationReport(brier, ece, bins, shape)


def bigrametric(confidences: list[float], outcomes: list[int | float], n_bins: int = 10) -> CalibrationReport:
    return big_report(confidences, outcomes, n_bins)


def shift_delta(
    base_conf: list[float],
    shifted_conf: list[float],
    base_out: list[int | float],
    shifted_out: list[int | float],
) -> dict[str, float]:
    """Robustness axis: how many of a scorer's competencies collapse under
    shift. Returns Brier/ECE on base vs shifted and the delta (positive =
    degradation)."""
    base = bigrametric(base_conf, base_out)
    shifted = bigrametric(shifted_conf, shifted_out)
    return {
        "brier_base": base.brier,
        "brier_shifted": shifted.brier,
        "brier_delta": shifted.brier - base.brier,
        "ece_base": base.ece,
        "ece_shifted": shifted.ece,
        "ece_delta": shifted.ece - base.ece,
    }

def cohens_kappa(rater_a: list[object], rater_b: list[object]) -> float:
    """Cohen's kappa: inter-rater agreement over chance (2 raters).

    Mirrors ``packages/substrate/src/eval.ts`` — the calibration gate for
    virtual judges (Airbnb target: high-80s-90s agreement). 1 = perfect,
    0 = chance-level, negative = below chance.
    """
    if len(rater_a) == 0:
        raise ValueError("empty")
    if len(rater_a) != len(rater_b):
        raise ValueError("length mismatch")
    n = len(rater_a)
    labels = set(rater_a) | set(rater_b)
    if not labels:
        raise ValueError("empty labels")

    observed = sum(1 for a, b in zip(rater_a, rater_b) if a == b) / n

    a_counts = {v: rater_a.count(v) for v in labels}
    b_counts = {v: rater_b.count(v) for v in labels}
    expected = sum((a_counts[v] / n) * (b_counts[v] / n) for v in labels)

    if expected == 1:
        return 1.0 if observed == 1 else 0.0
    return (observed - expected) / (1 - expected)


def krippendorff_alpha(ratings: list[list[object | None]]) -> float:
    """Krippendorff's alpha (nominal): N units x R rater slots, None = missing.

    Ported exactly from the canonical ``krippendorff`` 0.8.1 reference
    implementation (coincidence matrix / random coincidence matrix /
    nominal distance, alpha = 1 - sum(o*d)/sum(e*d)). Verified against the
    package's documented example (nominal -> 0.691358).
    """
    import numpy as np

    if len(ratings) == 0:
        raise ValueError("empty")
    if any(len(unit) < 2 for unit in ratings):
        raise ValueError("need at least 2 raters")

    labels = {v for unit in ratings for v in unit if v is not None}
    if len(labels) <= 1:
        raise ValueError("need more than one value in the domain")
    domain = sorted(labels, key=str)
    idx = {v: i for i, v in enumerate(domain)}
    V = len(domain)

    value_counts = np.zeros((len(ratings), V), dtype=float)
    for u, unit in enumerate(ratings):
        for v in unit:
            if v is not None:
                value_counts[u, idx[v]] += 1

    if (value_counts.sum(axis=1) <= 1).all():
        raise ValueError("need at least one unit with values from at least two raters")

    o = np.zeros((V, V), dtype=float)
    for unit in value_counts:
        pairable = max(unit.sum(), 2)
        o += (np.outer(unit, unit) - np.diag(unit)) / (pairable - 1)

    n_v = o.sum(axis=0)
    e = (np.outer(n_v, n_v) - np.diag(n_v)) / (n_v.sum() - 1)

    d = np.ones((V, V)) - np.eye(V)
    obs = (o * d).sum()
    exp = (e * d).sum()
    if exp == 0:
        return 0.0
    return 1.0 - obs / exp
