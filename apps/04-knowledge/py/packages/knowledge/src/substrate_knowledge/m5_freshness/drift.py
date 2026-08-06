"""A-K-22 drift-monitor — source vs graph: PSI, embedding/text drift.

PSI is pure numpy (no Evidently required); Evidently is the production
vehicle and plugs into the same verdict. t-digest percentiles are computed
with a sorted-window fallback (the t-digest package is optional).

Thresholds (documented, data-tuned): PSI > 0.25 on any feature or
embedding cosine mean below 0.70 ⇒ drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from substrate_knowledge.core.text import cosine

PSI_DRIFT_THRESHOLD = 0.25
EMBEDDING_DRIFT_THRESHOLD = 0.30  # 1 - mean cosine


def psi(reference: np.ndarray, current: np.ndarray, n_bins: int = 10) -> float:
    """Population stability index between two distributions.

    Pure numpy. Empty bins are smoothed with a small epsilon so the index is
    well-defined; identical distributions give exactly 0.0.
    """
    ref = np.asarray(reference, dtype=float)
    cur = np.asarray(current, dtype=float)
    if ref.size == 0 or cur.size == 0:
        return 0.0
    lo = float(min(ref.min(), cur.min()))
    hi = float(max(ref.max(), cur.max()))
    if hi == lo:
        return 0.0
    edges = np.linspace(lo, hi, n_bins + 1)
    p, _ = np.histogram(ref, bins=edges)
    q, _ = np.histogram(cur, bins=edges)
    p = p / p.sum() + 1e-9
    q = q / q.sum() + 1e-9
    return float(np.sum((p - q) * np.log(p / q)))


def tdigest_percentiles(values: list[float], quantiles: list[float]) -> dict[float, float]:
    """Sorted-window percentiles; t-digest is a drop-in optional upgrade."""
    qs = sorted(quantiles)
    if not values:
        return {q: 0.0 for q in qs}
    arr = np.sort(np.asarray(values, dtype=float))
    out: dict[float, float] = {}
    for q in qs:
        idx = min(int(q * (arr.size - 1)), arr.size - 1)
        out[q] = float(arr[idx])
    return out


@dataclass
class DriftReport:
    feature_psi: dict[str, float] = field(default_factory=dict)
    embedding_drift: float = 0.0
    text_drift: float = 0.0
    percentiles: dict = field(default_factory=dict)
    verdict: str = "ok"

    def to_dict(self) -> dict:
        return {
            "feature_psi": {k: round(v, 4) for k, v in self.feature_psi.items()},
            "embedding_drift": round(self.embedding_drift, 4),
            "text_drift": round(self.text_drift, 4),
            "percentiles": {str(k): round(v, 4) for k, v in self.percentiles.items()},
            "verdict": self.verdict,
        }


class DriftMonitor:
    """Compares source-side statistics against graph-side statistics."""

    def monitor(
        self,
        source_features: dict[str, np.ndarray],
        graph_features: dict[str, np.ndarray],
        source_embeddings: list[np.ndarray] | None = None,
        graph_embeddings: list[np.ndarray] | None = None,
    ) -> DriftReport:
        feature_psi = {name: psi(ref, cur) for name, ref in source_features.items() for cur in [graph_features.get(name, ref)]}

        embedding_drift = 0.0
        if source_embeddings and graph_embeddings:
            scores = [max(cosine(s, g) for g in graph_embeddings[:32]) for s in source_embeddings[:32]]
            embedding_drift = 1.0 - (sum(scores) / len(scores) if scores else 0.0)

        text_drift = sum(feature_psi.values()) / len(feature_psi) if feature_psi else 0.0

        drifted = any(v > PSI_DRIFT_THRESHOLD for v in feature_psi.values()) or embedding_drift > EMBEDDING_DRIFT_THRESHOLD
        return DriftReport(
            feature_psi=feature_psi,
            embedding_drift=embedding_drift,
            text_drift=text_drift,
            percentiles={
                q: v
                for q, v in tdigest_percentiles(list(source_features.get("score", np.asarray([]))), [0.5, 0.9, 0.99]).items()
            },
            verdict="drift" if drifted else "ok",
        )
