"""A-T-17 evidence-features — extractor outputs + outcome history → feature rows.

Rows align with the A-T-06 feature registry (``trust.contracts``): every name
in ``FEATURE_NAMES`` gets a value. An absent signal channel is all zeros —
absence is NOT ``retrieval_kind_silent`` (silent means retrieval was checked
and found nothing); checkability is judged separately by the verifiability
gate (A-T-23).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

from trust.contracts import FEATURE_NAMES, FEATURE_REGISTRY_V1, RetrievalVerdict
from trust.extractors.schema_checker import SchemaCheck
from trust.extractors.tool_call_verifier import ToolCallVerdict


@dataclass
class OutcomeHistory:
    """Confirmed (features → outcome) pairs observed so far."""

    history: list[bool] = None  # type: ignore[assignment]
    recent_k: int = 8

    def __post_init__(self) -> None:
        if self.history is None:
            self.history = []

    @property
    def rate(self) -> float:
        if not self.history:
            return 0.5
        return float(np.mean(self.history))

    @property
    def recent_rate(self) -> float:
        if not self.history:
            return 0.5
        return float(np.mean(self.history[-self.recent_k :]))


@dataclass
class EvidenceFeatures:
    """One aligned feature row over the registry (A-T-17)."""

    features: dict[str, float]

    def to_row(self) -> dict[str, float]:
        return {name: float(self.features.get(name, 0.0)) for name in FEATURE_NAMES}

    def vector(self, names: list[str] | None = None) -> np.ndarray:
        names = names or FEATURE_NAMES
        return np.array([float(self.features.get(n, 0.0)) for n in names], dtype=float)


def build_evidence_features(
    tool: ToolCallVerdict | None = None,
    retrieval: RetrievalVerdict | None = None,
    schema: SchemaCheck | None = None,
    outcome_history: OutcomeHistory | None = None,
) -> EvidenceFeatures:
    """Assemble the registry-aligned feature row from whatever evidence exists."""
    features: dict[str, float] = {}
    if tool is not None:
        features["tool_call_ran"] = 1.0 if tool.ran else 0.0
        features["tool_call_success"] = 0.0 if tool.error else (1.0 if tool.ran else 0.0)
        features["tool_result_sign_ok"] = 1.0 if tool.result_sign else 0.0
        features["tool_result_schema_ok"] = 1.0 if tool.result_schema_ok else 0.0
        features["tool_error"] = 1.0 if tool.error else 0.0
    if retrieval is not None:
        features["retrieval_kind_support"] = 1.0 if retrieval.kind == "support" else 0.0
        features["retrieval_kind_contradict"] = 1.0 if retrieval.kind == "contradict" else 0.0
        features["retrieval_kind_silent"] = 1.0 if retrieval.kind == "silent" else 0.0
        features["retrieval_prob"] = float(np.clip(retrieval.prob, 0.0, 1.0))
    if schema is not None:
        features["schema_satisfied"] = 1.0 if schema.satisfied else 0.0
        features["schema_violation_missing"] = 1.0 if schema.violation_kind == "missing" else 0.0
        features["schema_violation_type"] = 1.0 if schema.violation_kind == "type" else 0.0
        features["schema_violation_enum"] = 1.0 if schema.violation_kind == "enum" else 0.0
    if outcome_history is not None:
        features["outcomes_history_rate"] = outcome_history.rate
        features["outcomes_history_n"] = float(len(outcome_history.history))
        features["outcomes_recent_rate"] = outcome_history.recent_rate
    return EvidenceFeatures(features)


def validate_against_registry(features: dict[str, float], registry: list[Any] | None = None) -> None:
    """A-T-06: reject unknown feature names; the registry is the contract."""
    known = {f.name for f in (registry or FEATURE_REGISTRY_V1)}
    unknown = set(features) - known
    if unknown:
        raise ValueError(f"features not in registry: {sorted(unknown)}")
