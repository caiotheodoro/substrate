"""M3 scorer: train → serve → POST /confidence returns the C5 shape with
explain (A-T-18/19/20)."""
import pytest
from fastapi.testclient import TestClient

from trust.confbench.tasks import generate_tasks, to_training_frame
from trust.registry import InMemoryModelRegistry, ModelCard
from trust.scorer.model import TrustScorer
from trust.scorer.serve import create_app
from trust.scorer.train import train_scorer


@pytest.fixture(scope="module")
def trained():
    tasks = generate_tasks(300, seed=5)
    features, labels = to_training_frame(tasks)
    return train_scorer(features, labels, cv_folds=3, seed=7, model_version="test-v1")


class TestScorerTraining:
    def test_score_in_unit_interval(self, trained):
        tasks = generate_tasks(20, seed=9)
        for t in tasks:
            s = trained.score(t.evidence.to_row())
            assert 0.0 <= s <= 1.0

    def test_explain_sum_equals_raw_logit(self, trained):
        import math

        import numpy as np

        tasks = generate_tasks(5, seed=9)
        for t in tasks:
            raw, _ = trained.predict_proba(t.evidence.to_row())
            explain = trained.explain(t.evidence.to_row())
            logit = math.log(raw / (1 - raw))
            assert abs(sum(explain.values()) - logit) < 0.05

    def test_calibrated_on_base(self, trained):
        tasks = generate_tasks(200, seed=11)
        confs = [trained.score(t.evidence.to_row()) for t in tasks]
        from trust.eval_core import brier_score, expected_calibration_error

        ece, _ = expected_calibration_error(confs, [int(t.outcome) for t in tasks])
        assert ece < 0.15
        assert brier_score(confs, [int(t.outcome) for t in tasks]) < 0.25

    def test_unknown_features_ignored(self, trained):
        row = generate_tasks(1, seed=1)[0].evidence.to_row()
        row["score"] = 99.9  # harness-side extra key must not break the C5 call
        assert 0.0 <= trained.score(row) <= 1.0


class TestScorerServe:
    def _app(self, trained):
        return create_app(lambda: TrustScorer(trained))

    def test_confidence_returns_c5(self, trained):
        client = TestClient(self._app(trained))
        t = generate_tasks(1, seed=3)[0]
        resp = client.post("/confidence", json={"decisionId": "d-test", "confidenceFeatures": t.evidence.to_row()})
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) == {"score", "band", "explain", "modelVersion"}
        assert 0.0 <= body["score"] <= 1.0
        assert body["band"] in ("execute-band", "escalation-band", "reject-band")
        assert body["modelVersion"] == "test-v1"
        assert isinstance(body["explain"], dict)

    def test_confidence_rejects_missing_decision_id(self, trained):
        client = TestClient(self._app(trained))
        resp = client.post("/confidence", json={"confidenceFeatures": {}})
        assert resp.status_code == 422

    def test_health(self, trained):
        client = TestClient(self._app(trained))
        assert client.get("/health").json() == {"status": "ok"}

    def test_model_info(self, trained):
        client = TestClient(self._app(trained))
        info = client.get("/model").json()
        assert info["modelVersion"] == "test-v1"
        assert "features" in info


class TestRegistryWiring:
    def test_save_and_load_artifact(self, trained):
        import joblib
        import tempfile

        reg = InMemoryModelRegistry()
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/trust-scorer-test-v1.joblib"
            joblib.dump(trained, path)
            reg.save_model(
                "trust-scorer",
                "test-v1",
                artifact=path,
                features=trained.features,
                card=ModelCard(
                    model_name="trust-scorer",
                    version="test-v1",
                    purpose="test",
                    trained_at="2026-01-01T00:00:00+00:00",
                    framework="lightgbm",
                    training_set="test",
                    features=trained.features,
                    calibrated_with="netcal",
                ),
                artifact_path=path,
            )
            loaded = joblib.load(reg.get_artifact("trust-scorer:test-v1"))
            assert loaded.model_version == "test-v1"
