"""Contract shapes mirroring ``@substrate/substrate`` (zod) so Python trusts the
same C2/C3/C5 shapes. Do not fork the shapes; extend via new versions.

C2  Decision record + gate primitive.
C3  Retrieval verdict (support / contradict / silent).
C5  Confidence API (:8020 POST /confidence).
C6  Scenario (05 synthetic worlds; consumed by the data side).

The VERIFICATION HIERARCHY lives in ``trust.confbench.models`` — non-evidence
features (logprobs / self-consistency / verbalized confidence) are represented
only as a *banned self-report channel*, never in the production feature set.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

GateVerdict = Literal["execute", "escalate", "reject"]


def gate(confidence: float, execute_threshold: float, reject_threshold: float) -> GateVerdict:
    """Two-threshold gate (drop-in for ``DecisionRecordSchema`` / 01's gate)."""
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence out of range: {confidence}")
    if execute_threshold < reject_threshold:
        raise ValueError("execute_threshold must be >= reject_threshold")
    if confidence >= execute_threshold:
        return "execute"
    if confidence < reject_threshold:
        return "reject"
    return "escalate"


def band_for(confidence: float, execute_threshold: float, reject_threshold: float) -> str:
    verdict = gate(confidence, execute_threshold, reject_threshold)
    return {"execute": "execute-band", "escalate": "escalation-band", "reject": "reject-band"}[verdict]


@dataclass(frozen=True)
class RetrievalVerdict:
    """C3 — produced by 04's grounded gate, consumed here as a feature."""

    kind: Literal["support", "contradict", "silent"]
    prob: float
    citedEvidence: str | None
    claim: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "prob": float(self.prob),
            "citedEvidence": self.citedEvidence,
            "claim": self.claim,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RetrievalVerdict":
        kind = data["kind"]
        if kind not in ("support", "contradict", "silent"):
            raise ValueError(f"bad verdict kind: {kind}")
        return cls(
            kind=kind,
            prob=float(data["prob"]),
            citedEvidence=data.get("citedEvidence"),
            claim=data.get("claim") or "",
        )


@dataclass
class DecisionRecord:
    """C2 — one gated decision, logged by the harness (01) and consumed by the
    recalibration loop (M5)."""

    decisionId: str
    turnId: str
    action: str
    confidenceFeatures: dict[str, Any]
    verdict: GateVerdict
    outcome: bool | None = None
    confirmedAt: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "decisionId": self.decisionId,
            "turnId": self.turnId,
            "action": self.action,
            "confidenceFeatures": self.confidenceFeatures,
            "verdict": self.verdict,
            "outcome": self.outcome,
            "confirmedAt": self.confirmedAt,
        }


@dataclass
class ConfidenceRequest:
    """C5 request body for POST /confidence."""

    decisionId: str
    confidenceFeatures: dict[str, Any]


@dataclass
class ConfidenceResponse:
    """C5 response body. ``explain`` is per-feature contribution, for the
    escalation surface."""

    score: float
    band: str
    explain: dict[str, Any]
    modelVersion: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": float(self.score),
            "band": self.band,
            "explain": self.explain,
            "modelVersion": self.modelVersion,
        }


@dataclass
class ShockScenario:
    """C6 — a synthetic world seed used by the gated-data pipeline (M04)."""

    id: str
    name: str
    realizedOutcome: str
    window: str
    seed: str
    series: list[str]
    version: str = "1"
    source: str = "05-simulation"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "realizedOutcome": self.realizedOutcome,
            "window": self.window,
            "seed": self.seed,
            "series": self.series,
            "version": self.version,
            "source": self.source,
        }


@dataclass
class FeatureDef:
    """A registration in the feature registry (A-T-06)."""

    name: str
    kind: Literal["continuous", "fraction", "binary", "categorical", "text"]
    origin: Literal["tool", "retrieval", "schema", "outcome", "derived"]
    min: float | None = None
    max: float | None = None
    description: str = ""
    version: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "origin": self.origin,
            "min": self.min,
            "max": self.max,
            "description": self.description,
            "version": self.version,
        }


# The canonical v1 feature set. Extension = new version, never rename-in-place.
FEATURE_REGISTRY_V1: list[FeatureDef] = [
    FeatureDef("tool_call_ran", "binary", "feature", 0, 1, "a tool-call was issued for this action"),
    FeatureDef("tool_call_success", "binary", "feature", 0, 1, "the tool returned without an error"),
    FeatureDef("tool_result_sign_ok", "binary", "feature", 0, 1, "result sign matches expected"),
    FeatureDef("tool_result_schema_ok", "binary", "feature", 0, 1, "result satisfies its result schema"),
    FeatureDef("tool_error", "binary", "feature", 0, 1, "the tool returned (or raised) an error"),
    FeatureDef("retrieval_kind_support", "binary", "retrieval", 0, 1, "retrieval supports the claim"),
    FeatureDef("retrieval_kind_contradict", "binary", "retrieval", 0, 1, "retrieval contradicts the claim"),
    FeatureDef("retrieval_kind_silent", "binary", "retrieval", 0, 1, "retrieval is silent on the claim"),
    FeatureDef("retrieval_prob", "fraction", "retrieval", 0, 1, "verdict model probability (recalibrated)"),
    FeatureDef("schema_satisfied", "binary", "schema", 0, 1, "output satisfies the action schema"),
    FeatureDef("schema_violation_missing", "binary", "schema", 0, 1, "violation: required field missing"),
    FeatureDef("schema_violation_type", "binary", "schema", 0, 1, "violation: type mismatch"),
    FeatureDef("schema_violation_enum", "binary", "schema", 0, 1, "violation: enum/format mismatch"),
    FeatureDef("outcomes_history_rate", "fraction", "outcome", 0, 1, "confirmed-outcome rate in local history"),
    FeatureDef("outcomes_history_n", "continuous", "outcome", 0, None, "size of outcome history window"),
    FeatureDef("outcomes_recent_rate", "fraction", "outcome", 0, 1, "confirmed-outcome rate of last k"),
]

FEATURE_NAMES = [f.name for f in FEATURE_REGISTRY_V1]