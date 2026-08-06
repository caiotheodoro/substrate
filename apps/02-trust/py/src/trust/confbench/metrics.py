"""A-T-09 confbench-metrics — score-level calibration + ranking utility axes.

Calibration (Brier / ECE / reliability diagram) and NDCG-escalation.

Design decision (escalation semantics): NDCG-escalation ranks decisions by
confidence ASCENDING — a review budget is spent on the decisions the gate is
most unsure about, so a *well-calibrated* channel must place the failures
first. A channel that is confidently-wrong (self-report under shift) will
place failures at the *bottom* of the review order and collapse on this axis.
(The shared ``eval_core.ndcg_escalation`` primitive ranks descending — the
"surprise" diagnostic; ConfBench uses the ascending review-order metric
below.)

Reliability diagrams are written with matplotlib when available; tests never
require it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from trust.eval_core import big_report, expected_calibration_error, ndcg_at_k


def ndcg_escalation(confidence: list[float], worth: list[int | float], k: int | None = None) -> float:
    """Review-order NDCG: rank by confidence ascending, relevance 1 = the
    decision failed (outcome 0). A calibrated channel maximizes this.

    ``k=None`` uses the full ranking; ``ndcg_escalation_curve`` reports
    budget-limited values (a human review budget is a fixed small k), and
    ``evaluate_scorer`` headlines the mean over those budgets — full-ranking
    NDCG saturates near 1.0 and no longer discriminates channels."""
    if len(confidence) != len(worth):
        raise ValueError("length mismatch")
    order = sorted(range(len(confidence)), key=lambda i: confidence[i])
    return ndcg_at_k(list(worth), k or len(worth), order)


def ndcg_escalation_curve(
    confidence: list[float], worth: list[int | float], ks: list[int] | None = None, n: int | None = None
) -> dict[int, float]:
    """Budget-limited escalation NDCG: review budgets are fractions of the
    workload (5/10/20/40%) capped at [10, 25, 50, 100]."""
    total = n or len(confidence)
    budgets = [max(10, int(total * f)) for f in (0.05, 0.1, 0.2, 0.4)]
    ks = ks or list(dict.fromkeys(budgets))
    return {k: ndcg_escalation(confidence, worth, k) for k in ks if k <= len(confidence)}


def escalation_worth(tasks_outcomes: list[bool]) -> list[int]:
    """Relevance for the escalation axis: 1 = the decision failed."""
    return [0 if y else 1 for y in tasks_outcomes]


@dataclass
class ScorerEval:
    """Per-scorer evaluation on one task distribution (A-T-09)."""

    name: str
    brier: float
    ece: float
    bins: list[Any] = field(default_factory=list)
    ndcg_escalation: float = 0.0
    ndcg_curve: dict[int, float] = field(default_factory=dict)
    coverage: float = 0.0
    banned: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "brier": round(self.brier, 6),
            "ece": round(self.ece, 6),
            "ndcg_escalation": round(self.ndcg_escalation, 6),
            "ndcg_curve": {str(k): round(v, 6) for k, v in self.ndcg_curve.items()},
            "banned": self.banned,
        }


def evaluate_scorer(name: str, confidence: list[float], outcomes: list[bool], *, banned: bool = False) -> ScorerEval:
    """Score-level calibration + escalation utility for one scorer/channel.

    ``ndcg_escalation`` is the mean over budget-limited review budgets (the
    headline ranking-utility number)."""
    if len(confidence) != len(outcomes):
        raise ValueError("length mismatch")
    report = big_report(confidence, outcomes)
    worth = escalation_worth(outcomes)
    curve = ndcg_escalation_curve(confidence, worth)
    mean_ndcg = float(np.mean(list(curve.values()))) if curve else 0.0
    return ScorerEval(
        name=name,
        brier=report.brier,
        ece=report.ece,
        bins=report.bins,
        ndcg_escalation=mean_ndcg,
        ndcg_curve=curve,
        banned=banned,
    )


def reliability_diagram(evaluations: list[ScorerEval], path: str) -> bool:
    """Write a reliability diagram PNG; False when matplotlib is missing."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.plot([0, 1], [0, 1], "k--", linewidth=1, label="perfect")
    for ev in evaluations:
        xs = [b.confidence for b in ev.bins if b.count > 0]
        ys = [b.accuracy for b in ev.bins if b.count > 0]
        if xs:
            ax.plot(xs, ys, marker="o", markersize=3, label=f"{ev.name} (ECE {ev.ece:.3f})")
    ax.set_xlabel("confidence")
    ax.set_ylabel("accuracy")
    ax.set_title("Reliability diagram")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return True
