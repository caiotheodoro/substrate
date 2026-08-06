"""A-T-19 scorer model — LightGBM on evidence features + calibrated score.

Prediction path (C5 ``POST /confidence``):

1. registry-aligned feature vector (A-T-06 names, unknown keys rejected)
2. LightGBM probability ``p`` (binary objective)
3. netcal calibration of ``p`` -> final score
4. per-feature explanation from LightGBM ``pred_contrib`` (logit-space
   contributions; they sum to the raw logit — the calibrated score sits on
   top of it)
5. band from the two-threshold gate (C2 semantics)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import numpy as np

from trust.contracts import FEATURE_NAMES, band_for
from trust.scorer.calibrate import Calibrator


@dataclass
class TrainedScorer:
    """Everything needed to serve one model version."""

    features: list[str]
    booster: Any
    calibrator: Calibrator
    execute_threshold: float = 0.7
    reject_threshold: float = 0.3
    model_version: str = "v1"

    def predict_proba(self, features: dict[str, float]) -> tuple[float, np.ndarray]:
        # C5 confidenceFeatures may carry harness-side extras (score, cost,
        # routing); only registry names enter the model.
        X = np.array([[float(features.get(n, 0.0)) for n in self.features]], dtype=float)
        raw = float(self.booster.predict(X)[0])
        contribs = self.booster.predict(X, pred_contrib=True)[0]
        return raw, contribs

    def score(self, features: dict[str, float]) -> float:
        raw, _ = self.predict_proba(features)
        return float(np.clip(self.calibrator.transform(np.array([[raw]], dtype=float))[0], 0.0, 1.0))

    def explain(self, features: dict[str, float]) -> dict[str, float]:
        """Logit-space per-feature contribution; ``_intercept`` is the model
        base value, so ``sum(explain.values())`` reconstructs the raw logit."""
        _, contribs = self.predict_proba(features)
        out: dict[str, float] = {}
        for name, c in zip(self.features, contribs[:-1]):
            out[name] = float(c)
        out["_intercept"] = float(contribs[-1])
        return out

    def response(self, decision_id: str, features: dict[str, float]) -> dict[str, Any]:
        """The C5 payload."""
        score = self.score(features)
        return {
            "decisionId": decision_id,
            "score": round(score, 6),
            "band": band_for(score, self.execute_threshold, self.reject_threshold),
            "explain": self.explain(features),
            "modelVersion": self.model_version,
        }


class TrustScorer:
    """Stateless wrapper used by the registry and the service layer."""

    def __init__(self, trained: TrainedScorer) -> None:
        self.trained = trained

    def score(self, features: dict[str, float]) -> float:
        return self.trained.score(features)

    def explain(self, features: dict[str, float]) -> dict[str, float]:
        return self.trained.explain(features)

    @property
    def model_version(self) -> str:
        return self.trained.model_version


def scorer_from_file(path: str) -> TrustScorer:
    import joblib

    return TrustScorer(joblib.load(path))


def score_from_json(path: str) -> dict[str, Any]:
    data = json.loads(path)
    return data
