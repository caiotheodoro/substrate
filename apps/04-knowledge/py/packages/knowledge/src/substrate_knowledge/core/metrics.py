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