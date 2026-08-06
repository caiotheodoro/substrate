"""A-K-26 grounded-gate-service — svc :8204.

POST /gate {claim, subgraph} -> C3 RetrievalVerdict, or `blocked` when the
request cannot be grounded (empty/too-short claim, empty subgraph). Blocked
requests go to the veto log. The verdict (and the veto) is recorded in the
verdict store, which feeds 02.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from substrate_knowledge.core.storage import InMemoryStore, PostgresStore, Store
from substrate_knowledge.core.verdicts import RetrievalVerdict
from substrate_knowledge.m6_gate.verdict_classifier import DeterministicVerdictClassifier, VerdictClassifier
from substrate_knowledge.m6_gate.verdict_store import VerdictStore

MIN_CLAIM_TOKENS = 3


class GateRequest(BaseModel):
    claim: str = Field(min_length=1)
    subgraph: list[Any] | None = None


class GateResponse(BaseModel):
    verdict: RetrievalVerdict | None = None
    blocked: bool = False
    reason: str | None = None
    veto_id: str | None = None


class GroundedGateService:
    def __init__(
        self,
        classifier: VerdictClassifier | None = None,
        store: Store | None = None,
    ) -> None:
        self.classifier = classifier or DeterministicVerdictClassifier()
        self.verdict_store = VerdictStore(store or InMemoryStore())

    # ------------------------------------------------------------------
    def gate(self, claim: str, subgraph: list[Any] | None) -> GateResponse:
        evidence = self._evidence_texts(subgraph)
        if len(claim.split()) < MIN_CLAIM_TOKENS:
            return self._blocked("claim too short to ground")
        if not evidence:
            return self._blocked("empty subgraph: no evidence to ground the claim against")

        verdict = self.classifier.classify(claim, evidence)
        self.verdict_store.record(verdict)
        return GateResponse(verdict=verdict)

    def _blocked(self, reason: str) -> GateResponse:
        veto_id = f"veto:{uuid.uuid4().hex[:12]}"
        self._veto_store().put(
            veto_id,
            {"reason": reason, "ts": time.time(), "id": veto_id},
        )
        return GateResponse(blocked=True, reason=reason, veto_id=veto_id)

    def vetoes(self) -> list[dict[str, Any]]:
        return [value for _, value in self._veto_store().scan("veto:")]

    def _veto_store(self) -> Store:
        # The veto log reuses the verdict store's backing store.
        return self.verdict_store.store

    @staticmethod
    def _evidence_texts(subgraph: list[Any] | None) -> list[str]:
        texts: list[str] = []
        if not subgraph:
            return texts
        for item in subgraph:
            if isinstance(item, str):
                texts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    texts.append(str(text))
        return texts


def build_gate_app(service: GroundedGateService | None = None) -> FastAPI:
    svc = service or GroundedGateService()

    app = FastAPI(title="grounded-gate", version="0.1.0")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "service": "grounded-gate", "port": 8204}

    @app.post("/gate", response_model=GateResponse)
    def gate(req: GateRequest) -> GateResponse:
        return svc.gate(req.claim, req.subgraph)

    @app.get("/gate/vetoes")
    def vetoes() -> list[dict[str, Any]]:
        return svc.vetoes()

    return app


def claim_fingerprint(claim: str) -> str:
    return hashlib.sha256(claim.strip().lower().encode("utf-8")).hexdigest()[:16]
