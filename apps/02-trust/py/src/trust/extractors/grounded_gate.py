"""Joint 2 (C3): 04's grounded gate (:8204) as the top of 02's A-T-15 ladder.

The grounded gate produces evidence-cited verdicts against a subgraph — the
strongest signal in the hierarchy. 02 consumes them over HTTP; when 04 is
unreachable (offline tests, compose not up) the rung degrades to ``silent``
with prob 0.0 and the ladder falls through to the next rung — the verdict
feature simply carries no retrieval support that turn.

The rung is a ``VerdictModelProtocol`` so it drops into ``RetrievalLadder``
with zero changes to the ladder logic.
"""
from __future__ import annotations

from typing import Any

from trust.contracts import RetrievalVerdict
from trust.model_backend import VerdictModelProtocol

DEFAULT_GROUNDED_GATE_URL = "http://localhost:8204"


class GroundedGateRung:
    """Ladder rung backed by 04's ``POST :8204/gate`` (C3 response)."""

    name = "grounded-gate"

    def __init__(self, base_url: str = DEFAULT_GROUNDED_GATE_URL, timeout: float = 10.0) -> None:
        self.base_url = base_url
        self.timeout = timeout

    def verdict(self, claim: str, passages: list[str], temperature: float = 0.0) -> RetrievalVerdict:
        try:
            import httpx

            resp = httpx.post(
                f"{self.base_url.rstrip('/')}/gate",
                json={"claim": claim, "subgraph": passages},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            body: dict[str, Any] = resp.json()
        except Exception:
            return RetrievalVerdict(kind="silent", prob=0.0, citedEvidence=None, claim=claim)

        if body.get("blocked"):
            return RetrievalVerdict(kind="silent", prob=0.0, citedEvidence=None, claim=claim)
        verdict = body.get("verdict")
        if not verdict:
            return RetrievalVerdict(kind="silent", prob=0.0, citedEvidence=None, claim=claim)
        return RetrievalVerdict(
            kind=str(verdict["kind"]),
            prob=float(verdict["prob"]),
            citedEvidence=str(verdict.get("citedEvidence")),
            claim=str(verdict.get("claim") or claim),
        )


def build_grounded_gate_rung(base_url: str = DEFAULT_GROUNDED_GATE_URL) -> VerdictModelProtocol:
    """Factory for the production ladder: HHEM → Glider → Lynx → grounded gate."""
    return GroundedGateRung(base_url=base_url)


def summarize_grounded_verdict(verdict: RetrievalVerdict) -> dict[str, Any]:
    """The C3 summary that feeds A-T-17 evidence features."""
    return verdict.as_dict()
