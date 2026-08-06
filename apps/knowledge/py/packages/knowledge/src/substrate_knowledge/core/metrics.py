"""Eval-core primitives — Python mirror of `packages/substrate/src/eval.ts`.

A gate is a deployment of an eval; an eval is a gate in rehearsal. These pure
scorers are shared by the extraction harness (A-K-07), the resolution
calibrator (A-K-13), the characterization suite (A-K-03), and the gate
effectiveness benchmarks.
"""

from __future__ import annotations

import math


def brier_score(confidences: list[float], outcomes: list[int]) -> float:
    """Brier score for calibrated binary confidence. Lower is better."""
    if not confidences:
        raise ValueError("empty")
    if len(confidences) != len(outcomes):
        raise ValueError("length mismatch")
    return sum((c - o) ** 2 for c, o in zip(confidences, outcomes)) / len(confidences)


def expected_calibration_error(
    confidences: list[float], outcomes: list[int], n_bins: int = 10
) -> dict:
    if not confidences:
        raise ValueError("empty")
    if len(confidences) != len(outcomes):
        raise ValueError("length mismatch")
    if n_bins <= 0:
        raise ValueError("n_bins must be positive")
    bins = [
        {"lower": i / n_bins, "upper": (i + 1) / n_bins, "accuracy": 0.0, "confidence": 0.0, "count": 0}
        for i in range(n_bins)
    ]
    for c, o in zip(confidences, outcomes):
        idx = min(int(min(c, 1 - 1e-9) * n_bins), n_bins - 1)
        bins[idx]["confidence"] += c
        bins[idx]["accuracy"] += float(o)
        bins[idx]["count"] += 1
    ece = 0.0
    for b in bins:
        if b["count"] == 0:
            continue
        b["accuracy"] /= b["count"]
        b["confidence"] /= b["count"]
        ece += (b["count"] / len(confidences)) * abs(b["accuracy"] - b["confidence"])
    return {"ece": ece, "bins": bins}


def coverage(realized: list[float], lower: list[float], upper: list[float], level: float) -> float:
    if not (len(realized) == len(lower) == len(upper)):
        raise ValueError("length mismatch")
    if not realized:
        return 0.0
    hits = sum(1 for r, lo, hi in zip(realized, lower, upper) if lo <= r <= hi)
    return hits / len(realized)


def precision_recall_f1(matched: int, extracted: int, labeled: int) -> tuple[float, float, float]:
    p = matched / extracted if extracted else 0.0
    r = matched / labeled if labeled else 0.0
    f1 = 2 * p * r / (p + r) if p + r > 0 else 0.0
    return p, r, f1

def cohens_kappa(rater_a: list[object], rater_b: list[object]) -> float:
    """Cohen's kappa: inter-rater agreement over chance (2 raters).

    Mirrors ``packages/substrate/src/eval.ts`` — used to calibrate the
    verdict classifier against human labels (Airbnb target: high-80s-90s
    agreement). 1 = perfect, 0 = chance, negative = below chance.
    """
    if not rater_a:
        raise ValueError("empty")
    if len(rater_a) != len(rater_b):
        raise ValueError("length mismatch")
    n = len(rater_a)
    labels = set(rater_a) | set(rater_b)
    if not labels:
        raise ValueError("empty labels")

    observed = sum(1 for a, b in zip(rater_a, rater_b) if a == b) / n
    expected = sum((rater_a.count(v) / n) * (rater_b.count(v) / n) for v in labels)
    if expected == 1:
        return 1.0 if observed == 1 else 0.0
    return (observed - expected) / (1 - expected)


def krippendorff_alpha(ratings: list[list[object | None]]) -> float:
    """Krippendorff's alpha (nominal): N units x R rater slots, None = missing.

    Ported exactly from the canonical ``krippendorff`` 0.8.1 reference
    implementation; verified against its documented example (0.691358).
    """
    import numpy as np

    if not ratings:
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
