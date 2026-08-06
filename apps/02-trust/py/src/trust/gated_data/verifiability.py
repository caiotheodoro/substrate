"""A-T-23 verifiability-gate — per-sample "checkable AND true".

Checkable: the sample carries at least one of the four evidence channels
(tool / retrieval / schema / outcome). True: the channel verdicts agree with
the sample's label. Samples that are neither checkable nor true are rejected
(they are not evidence, they are vibes — the R2 audit quantifies how often
this binds).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from trust.gated_data.models import GateVerdictResult, SeedRecord


@dataclass
class VerifiabilityVerdict:
    checkable: bool
    verified: bool
    signals: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"checkable": self.checkable, "verified": self.verified, "signals": self.signals}


def assess_verifiability(seed: SeedRecord) -> VerifiabilityVerdict:
    """Per-sample check: which channels exist, and do they back the label?"""
    signals: dict[str, Any] = {}
    meta = seed.metadata or {}
    kinds = set(seed.signal_kinds or [])

    if "tool" in kinds or "tool" in meta:
        signals["tool"] = _tool_agrees(seed)
    if "retrieval" in kinds or "retrieval" in meta:
        signals["retrieval"] = _retrieval_agrees(seed)
    if "schema" in kinds or "schema" in meta:
        signals["schema"] = _schema_agrees(seed)
    if "outcome" in kinds or "outcome" in meta:
        signals["outcome"] = meta.get("outcome_rate", 0.5) >= 0.5 == seed.label

    checkable = bool(signals)
    verified = checkable and all(v for v in signals.values())
    return VerifiabilityVerdict(checkable=checkable, verified=verified, signals=signals)


def _tool_agrees(seed: SeedRecord) -> bool:
    meta = seed.metadata or {}
    if meta.get("tool_error"):
        return False
    if meta.get("tool_result_sign") is not None and seed.label and meta.get("tool_result_sign") != "positive":
        return False
    return True


def _retrieval_agrees(seed: SeedRecord) -> bool:
    meta = seed.metadata or {}
    kind = meta.get("retrieval_kind", "silent")
    if kind == "contradict":
        return False
    if kind == "support":
        return seed.label
    return False


def _schema_agrees(seed: SeedRecord) -> bool:
    meta = seed.metadata or {}
    return not (meta.get("schema_violation") is not None) and seed.label


class VerifiabilityGate:
    """Gate over seed records using the extractor semantics (A-T-23)."""

    def __init__(self, require_checkable: bool = True, require_verified: bool = True) -> None:
        self.require_checkable = require_checkable
        self.require_verified = require_verified

    def evaluate(self, seed: SeedRecord) -> GateVerdictResult:
        verdict = assess_verifiability(seed)
        reasons: list[str] = []
        if self.require_checkable and not verdict.checkable:
            reasons.append("not checkable")
        if self.require_verified and not verdict.verified:
            reasons.append("not verified")
        passed = not reasons
        return GateVerdictResult(
            gate="verifiability",
            passed=passed,
            reason="; ".join(reasons) or "ok",
            detail=verdict.as_dict(),
        )
