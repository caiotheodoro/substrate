"""A-T-06 feature-registry and A-T-20 model-registry (v1-lite).

Both are table-backed with an in-memory implementation for tests and a
Postgres-backed implementation for ``docker compose up`` (see ``trust.db``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from trust.contracts import FEATURE_REGISTRY_V1, FeatureDef

UTC = timezone.utc


class FeatureRegistry(Protocol):
    def register(self, feature: FeatureDef) -> None: ...
    def get(self, name: str) -> FeatureDef: ...
    def list(self) -> list[FeatureDef]: ...
    def hash(self) -> str: ...


class InMemoryFeatureRegistry:
    """A-T-06 — feature_defs / feature_versions tables (in-memory)."""

    def __init__(self, seed: list[FeatureDef] | None = None) -> None:
        self._defs: dict[str, FeatureDef] = {f.name: f for f in (seed or FEATURE_REGISTRY_V1)}
        self._versions: list[FeatureDef] = list(self._defs.values())

    def register(self, feature: FeatureDef) -> None:
        prev = self._defs.get(feature.name)
        if prev is not None:
            feature.version = prev.version + 1
        self._defs[feature.name] = feature
        self._versions.append(feature)

    def get(self, name: str) -> FeatureDef:
        if name not in self._defs:
            raise KeyError(f"unknown feature: {name}")
        return self._defs[name]

    def list(self) -> list[FeatureDef]:
        return list(self._defs.values())

    def hash(self) -> str:
        import hashlib

        blob = "\n".join(sorted(f.name for f in self._defs.values()))
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


@dataclass
class ModelCard:
    model_name: str
    version: str
    purpose: str
    trained_at: str
    framework: str
    training_set: str
    features: list[str]
    calibrated_with: str
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "version": self.version,
            "purpose": self.purpose,
            "trained_at": self.trained_at,
            "framework": self.framework,
            "training_set": self.training_set,
            "features": self.features,
            "calibrated_with": self.calibrated_with,
            "notes": self.notes,
        }


@dataclass
class RegisteredModel:
    model_id: str
    name: str
    version: str
    features: list[str]
    artifact_path: str
    card: ModelCard
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "name": self.name,
            "version": self.version,
            "features": self.features,
            "artifact_path": self.artifact_path,
            "card": self.card.as_dict(),
            "created_at": self.created_at,
        }


class ModelRegistry(Protocol):
    def save_model(
        self,
        name: str,
        version: str,
        artifact: Any,
        features: list[str],
        card: ModelCard,
        artifact_path: str,
    ) -> RegisteredModel: ...
    def load_artifact(self, model_id: str) -> Any: ...
    def get(self, model_id: str) -> RegisteredModel: ...
    def list(self) -> list[RegisteredModel]: ...
    def latest(self, name: str) -> RegisteredModel: ...


class InMemoryModelRegistry:
    """A-T-20 v1-lite — models / model_versions / model_cards in memory + an
    object-store interface (MinIO at ``compose``; stub here)."""

    def __init__(self, object_store: Any = None) -> None:
        self._models: dict[str, RegisteredModel] = {}
        self._artifacts: dict[str, Any] = {}
        self._store = object_store

    def save_model(
        self,
        name: str,
        version: str,
        artifact: Any,
        features: list[str],
        card: ModelCard,
        artifact_path: str,
    ) -> RegisteredModel:
        model_id = f"{name}:{version}"
        reg = RegisteredModel(
            model_id=model_id,
            name=name,
            version=version,
            features=features,
            artifact_path=artifact_path,
            card=card,
        )
        self._models[model_id] = reg
        self._artifacts[model_id] = artifact
        if self._store is not None:
            self._store.put(artifact_path, artifact)
        return reg

    def get(self, model_id: str) -> RegisteredModel:
        if model_id not in self._models:
            raise KeyError(f"unknown model {model_id}")
        return self._models[model_id]

    def get_artifact(self, model_id: str) -> Any:
        if model_id not in self._artifacts:
            raise KeyError(f"no artifact for {model_id}")
        return self._artifacts[model_id]

    def list(self) -> list[RegisteredModel]:
        return sorted(self._models.values(), key=lambda m: m.created_at, reverse=True)

    def latest(self, name: str) -> RegisteredModel:
        matches = [m for m in self._models.values() if m.name == name]
        if not matches:
            raise KeyError(f"no versions of {name}")
        return sorted(matches, key=lambda m: m.version)[-1]