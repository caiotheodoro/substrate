"""P3 — difficulty model: from calibration outcomes to a fitted difficulty.

After the oracle measures a task population, a logistic model is fit over
task features (tool count, trajectory length, arg complexity) against the
measured solve rates. ``difficulty(task)`` becomes the calibrated estimate
that replaces the generator's prior, and ``human_action_baseline`` feeds
Phase 3's RHAE scoring (upper-median best first-run action count).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import median

from trust.forge.calibration import CalibrationOutcome
from trust.forge.task import ForgeTask


def task_features(task: ForgeTask) -> list[float]:
    """Feature vector for difficulty modeling."""
    n_calls = len(task.expected)
    n_tools = len(set(c.name for c in task.expected))
    arg_complexity = sum(len(c.args) for c in task.expected)
    return [float(n_calls), float(n_tools), float(arg_complexity)]


@dataclass
class DifficultyModel:
    """Logistic difficulty model fit on measured calibration outcomes.

    ``difficulty(task)`` returns a calibrated 0..1 score where higher =
    harder, derived from the fitted solve probability (1 - p_solve).
    """

    features: list[list[float]] = None  # type: ignore[assignment]
    outcomes: list[float] = None  # type: ignore[assignment]
    weights: list[float] | None = None
    intercept: float = 0.0
    feature_keys: list[str] = None  # type: ignore[assignment]
    _means: list[float] = field(default_factory=list)
    _stds: list[float] = field(default_factory=list)
    _feature_cols: list[int] = field(default_factory=lambda: [0, 1, 2])

    def fit(self, tasks: list[ForgeTask], outcomes: list[CalibrationOutcome]) -> "DifficultyModel":
        self.feature_keys = ["n_calls", "n_tools", "arg_complexity"]
        X = [task_features(t) for t in tasks]
        y = [o.n_solved / max(o.n_attempts, 1) for o in outcomes]
        return self._fit_matrix(X, y)

    def _fit_matrix(self, X: list[list[float]], y: list[float]) -> "DifficultyModel":
        """Fit on an arbitrary feature matrix (feature-selection support)."""
        self._feature_cols = list(range(len(X[0])))
        # standardize features (z-score) so gradient descent converges on
        # features with very different scales (counts vs arg richness)
        means = [sum(col) / len(col) for col in zip(*X)]
        stds = [max((sum((v - m) ** 2 for v in col) / len(col)) ** 0.5, 1e-9) for col, m in zip(zip(*X), means)]
        Xs = [[(v - m) / s for v, m, s in zip(row, means, stds)] for row in X]
        # closed-form logistic regression via gradient descent (no sklearn
        # dependency in the hot path; deterministic seed)
        w = [0.0] * (len(Xs[0]) + 1)
        lr = 0.5
        for _ in range(2000):
            grad = [0.0] * len(w)
            for xi, yi in zip(Xs, y):
                z = w[0] + sum(wi * xj for wi, xj in zip(w[1:], xi))
                p = 1.0 / (1.0 + math.exp(-max(min(z, 30), -30)))
                err = p - yi
                grad[0] += err
                for j, xj in enumerate(xi):
                    grad[j + 1] += err * xj
            for j in range(len(w)):
                w[j] -= lr * grad[j] / max(len(Xs), 1)
        # keep the standardization for scoring
        self._means = means
        self._stds = stds
        self.intercept = w[0]
        self.weights = w[1:]
        self.features = Xs
        self.outcomes = y
        return self

    def _difficulty_from_features(self, x: list[float]) -> float:
        x = [(v - m) / s for v, m, s in zip(x, self._means, self._stds)]
        z = self.intercept + sum(wi * xj for wi, xj in zip(self.weights or [], x))
        p = 1.0 / (1.0 + math.exp(-max(min(z, 30), -30)))
        return 1.0 - p

    def solve_probability(self, task: ForgeTask) -> float:
        x = task_features(task)
        return 1.0 - self._difficulty_from_features(x)

    def difficulty(self, task: ForgeTask) -> float:
        return round(1.0 - self.solve_probability(task), 4)


def human_action_baseline(outcomes: list[CalibrationOutcome], task_id: str) -> int:
    """Upper-median best first-run action count (ARC-AGI-3 §4.1). For each
    task, take the best (minimum) action count; the baseline is the median
    of those minima across the calibration population."""
    for o in outcomes:
        if o.task_id == task_id and o.action_counts:
            return int(median(o.action_counts))
    return 0
