"""A-S-01 — simbench-core: score an ensemble forecast against realized history.

Metrics (SPEC: "coverage at 50/80/95 · Brier · tail-loss vs baseline"):
  - coverage_50/80/95: fraction of horizon steps inside the nominal interval
  - brier: multi-threshold Brier (mean over q in 0.05..0.95 of (I - q)^2)
  - crps: empirical CRPS via the kernel representation (scoringrules when
    available, pure-python fallback otherwise)
  - tail_loss: downside exceedance at alpha (max(q_alpha - realized, 0))
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

LEVELS = (0.50, 0.80, 0.95)
BRIER_LEVELS = np.arange(0.05, 1.0, 0.05)


def _empirical_crps(values: np.ndarray, y: float) -> float:
    m = np.sort(np.asarray(values, dtype=float).ravel())
    n = m.size
    if n == 0:
        return 0.0
    first = float(np.mean(np.abs(m - y)))
    # pairwise mean distance via sorted cumsum trick
    weights = np.arange(1, n + 1) * 2 - (n + 1)
    second = float(np.sum(weights * m) / (n * n))
    return first - second


def crps_ensemble(values: np.ndarray, y: np.ndarray) -> float:
    """Mean empirical CRPS over horizon steps. Prefers scoringrules when
    installed and the backend imports cleanly."""
    try:
        from scoringrules import crps_ensemble as _crps

        return float(np.mean(_crps(np.asarray(values, dtype=float), np.asarray(y, dtype=float))))
    except Exception:
        return float(np.mean([_empirical_crps(values[:, t], float(y[t])) for t in range(values.shape[1])]))


def coverage(forecast, realized: np.ndarray, level: float) -> float:
    lo, hi = forecast.interval(level)
    inside = (realized >= lo) & (realized <= hi)
    return float(np.mean(inside))


def brier_score(forecast, realized: np.ndarray) -> float:
    scores = []
    for q in BRIER_LEVELS:
        threshold = forecast.quantile(float(q))
        hits = (realized <= threshold).astype(float)
        scores.append(float(np.mean((hits - q) ** 2)))
    return float(np.mean(scores))


def reliability(forecast, realized: np.ndarray) -> dict[str, float]:
    """Binned reliability: empirical coverage vs nominal for each level."""
    out = {}
    for level in LEVELS:
        out[f"cov_{int(level * 100)}"] = coverage(forecast, realized, level)
    return out


def tail_loss(forecast, realized: np.ndarray, alpha: float = 0.05) -> float:
    """Downside exceedance at alpha: how far realized fell below the alpha
    quantile (positive = tail break)."""
    q = forecast.quantile(alpha)
    return float(np.mean(np.maximum(q - realized, 0.0)))


@dataclass
class ScoreResult:
    scores: dict[str, float]
    meta: dict

    def to_dict(self) -> dict:
        return {"scores": self.scores, "meta": self.meta}


def score_ensemble(forecast, realized: np.ndarray, meta: dict | None = None) -> ScoreResult:
    realized = np.asarray(realized, dtype=float)
    if realized.shape[0] != forecast.values.shape[1]:
        raise ValueError(
            f"horizon mismatch: forecast={forecast.values.shape[1]} realized={realized.shape[0]}"
        )
    scores: dict[str, float] = {}
    for level in LEVELS:
        scores[f"coverage_{int(level * 100)}"] = coverage(forecast, realized, level)
    scores["brier"] = brier_score(forecast, realized)
    scores["crps"] = crps_ensemble(forecast.values, realized)
    scores["tail_loss"] = tail_loss(forecast, realized)
    scores.update(reliability(forecast, realized))
    return ScoreResult(scores=scores, meta=meta or {})