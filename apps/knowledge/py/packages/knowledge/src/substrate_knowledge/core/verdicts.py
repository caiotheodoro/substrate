"""C3 — retrieval verdict contract (Python mirror of packages/substrate).

Three states, never cosine-similarity-as-truth. Shape is frozen to match
`RetrievalVerdictSchema` in `@substrate/substrate`: kind + prob + citedEvidence + claim.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class VerdictKind(StrEnum):
    SUPPORT = "support"
    CONTRADICT = "contradict"
    SILENT = "silent"


class RetrievalVerdict(BaseModel):
    """C3 retrieval verdict. `prob` is a calibrated model probability (0..1)."""

    kind: VerdictKind
    prob: float = Field(ge=0.0, le=1.0)
    citedEvidence: str | None = None
    claim: str

    @field_validator("prob")
    @classmethod
    def _prob_in_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("prob must be in [0, 1]")
        return v

    def to_c3(self) -> dict[str, object]:
        """Byte-shape compatible with RetrievalVerdictSchema JSON."""
        return {
            "kind": self.kind.value,
            "prob": self.prob,
            "citedEvidence": self.citedEvidence,
            "claim": self.claim,
        }


def gate(confidence: float, execute_threshold: float, reject_threshold: float) -> str:
    """C2 gate primitive: two thresholds, escalation band between them."""
    if confidence >= execute_threshold:
        return "execute"
    if confidence < reject_threshold:
        return "reject"
    return "escalate"
