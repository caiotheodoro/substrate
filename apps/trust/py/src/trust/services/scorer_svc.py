"""A-T-19 :8020 scorer-serve — the C5 confidence endpoint (01's drop-in)."""
from __future__ import annotations

from trust.scorer.serve import create_app
from trust.services._common import run

PORT = 8020


def _provider():
    from trust.registry import InMemoryModelRegistry

    registry = InMemoryModelRegistry()
    try:
        import joblib

        model = registry.latest("trust-scorer")
        return __import__("trust.scorer.model", fromlist=["TrustScorer"]).TrustScorer(joblib.load(model.artifact_path))
    except Exception:
        from trust.scorer.serve import _uniform_fallback

        return _uniform_fallback()


app = create_app(_provider)


def main() -> None:
    run(app, PORT)
