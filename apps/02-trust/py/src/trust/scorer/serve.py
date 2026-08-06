"""A-T-19 scorer-serve — ``POST :8020/confidence``, C5 drop-in.

The confidence provider 01's gate and 03's tiering consume. The app is built
by ``create_app`` so tests can inject a trained scorer (or a registry-backed
provider) without a model file on disk.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from trust.contracts import ConfidenceRequest, ConfidenceResponse
from trust.scorer.model import TrainedScorer, TrustScorer

logger = logging.getLogger("trust.scorer.serve")

ScorerProvider = Callable[[], TrustScorer]


class _ConfidenceRequestModel(BaseModel):
    decisionId: str = Field(min_length=1)
    confidenceFeatures: dict[str, Any]


class _ConfidenceResponseModel(BaseModel):
    score: float
    band: str
    explain: dict[str, float]
    modelVersion: str


def create_app(provider: ScorerProvider, *, execute_threshold: float = 0.7, reject_threshold: float = 0.3) -> FastAPI:
    """FastAPI app with the model behind a provider callable (tests inject
    their own; production loads the latest registry version)."""
    app = FastAPI(title="trust-scorer", version="1.0.0", description="A-T-19 C5 confidence provider")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/model")
    def model_info() -> dict[str, Any]:
        scorer = provider()
        t: TrainedScorer = scorer.trained
        return {
            "modelVersion": t.model_version,
            "features": t.features,
            "calibrator": getattr(t.calibrator, "kind", type(t.calibrator).__name__),
            "executeThreshold": t.execute_threshold,
            "rejectThreshold": t.reject_threshold,
        }

    @app.post("/confidence", response_model=_ConfidenceResponseModel)
    def confidence(req: _ConfidenceRequestModel) -> _ConfidenceResponseModel:
        try:
            resp = provider().trained.response(req.decisionId, req.confidenceFeatures)
        except (ValueError, KeyError) as err:
            raise HTTPException(status_code=422, detail=str(err))
        return _ConfidenceResponseModel(**resp)

    return app


def _default_provider() -> TrustScorer:
    """Production provider: latest registered model, else a deterministic
    fallback (uniform prior) so the service boots without a model file."""
    try:
        from trust.registry import InMemoryModelRegistry

        registry = InMemoryModelRegistry()
        model = registry.latest("trust-scorer")
        return TrustScorer(_load(model.artifact_path))
    except Exception:  # pragma: no cover - boot fallback
        logger.warning("no registered model found; serving uniform-prior fallback")
        return _uniform_fallback()


def _load(path: str) -> TrainedScorer:
    import joblib

    return joblib.load(path)


def _uniform_fallback() -> TrustScorer:
    """Deterministic 0.5-everywhere fallback so the service boots without a
    trained model; the escalation band absorbs it until ``scorer-train`` runs."""
    import numpy as np

    from trust.scorer.calibrate import SklearnIsotonic
    from trust.scorer.model import TrainedScorer

    class _ConstantBooster:
        def predict(self, X: Any, pred_contrib: bool = False) -> Any:
            if pred_contrib:
                n = X.shape[0]
                return np.zeros((n, X.shape[1] + 1))
            return np.full(X.shape[0], 0.5)

    calibrator = SklearnIsotonic().fit(np.array([0.5]), np.array([1]))
    return TrustScorer(
        TrainedScorer(
            features=[],
            booster=_ConstantBooster(),
            calibrator=calibrator,
            model_version="fallback-uniform",
        )
    )


app = create_app(_default_provider)


def main() -> None:
    import uvicorn

    uvicorn.run("trust.scorer.serve:app", host="0.0.0.0", port=8020)
