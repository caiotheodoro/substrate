"""A-T-06 feature registry + A-T-20 model registry (v1-lite) behaviors."""
import pytest

from trust.contracts import FEATURE_NAMES, FEATURE_REGISTRY_V1, FeatureDef
from trust.registry import InMemoryFeatureRegistry, InMemoryModelRegistry, ModelCard


class TestFeatureRegistry:
    def test_seeded_with_v1(self):
        reg = InMemoryFeatureRegistry()
        assert set(reg.list().keys()) if hasattr(reg.list(), "keys") else True
        assert len(reg.list()) == len(FEATURE_REGISTRY_V1)
        assert all(f.name in FEATURE_NAMES for f in reg.list())

    def test_register_versions_up(self):
        reg = InMemoryFeatureRegistry()
        f = FeatureDef("tool_call_ran", "binary", "feature", 0, 1)
        reg.register(f)
        assert reg.get("tool_call_ran").version == 2
        assert reg.get("tool_call_ran").name == "tool_call_ran"

    def test_unknown_feature_raises(self):
        reg = InMemoryFeatureRegistry()
        with pytest.raises(KeyError):
            reg.get("nope")

    def test_hash_is_stable(self):
        reg = InMemoryFeatureRegistry()
        assert reg.hash() == reg.hash()
        assert len(reg.hash()) == 16


class TestModelRegistry:
    def _card(self, name="trust-scorer", version="v1") -> ModelCard:
        return ModelCard(
            model_name=name,
            version=version,
            purpose="C5 confidence provider",
            trained_at="2026-01-01T00:00:00+00:00",
            framework="lightgbm",
            training_set="confbench-train",
            features=FEATURE_NAMES,
            calibrated_with="netcal-isotonic",
        )

    def test_save_and_get(self):
        reg = InMemoryModelRegistry()
        reg.save_model("trust-scorer", "v1", artifact={"b": 1}, features=FEATURE_NAMES, card=self._card(), artifact_path="models/trust-scorer-v1.joblib")
        model = reg.get("trust-scorer:v1")
        assert model.model_id == "trust-scorer:v1"
        assert reg.get_artifact("trust-scorer:v1") == {"b": 1}

    def test_latest_by_version(self):
        reg = InMemoryModelRegistry()
        reg.save_model("trust-scorer", "v1", artifact=1, features=FEATURE_NAMES, card=self._card(version="v1"), artifact_path="m/v1")
        reg.save_model("trust-scorer", "v2", artifact=2, features=FEATURE_NAMES, card=self._card(version="v2"), artifact_path="m/v2")
        assert reg.latest("trust-scorer").version == "v2"
        assert len(reg.list()) == 2

    def test_unknown_model_raises(self):
        reg = InMemoryModelRegistry()
        with pytest.raises(KeyError):
            reg.get("missing:v1")
        with pytest.raises(KeyError):
            reg.latest("missing")
