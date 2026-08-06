"""A-T-15 :8011 retrieval-verdict — the HHEM→Glider→Lynx ladder over HTTP.

The service defaults to the deterministic stub ladder (offline-safe); when
the compose models are up, construct with ``create_app(real_ladder=True)``.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from trust.contracts import RetrievalVerdict
from trust.extractors.retrieval_ladder import RetrievalLadder, build_llm_ladder
from trust.model_backend import DeterministicVerdictBackend
from trust.services._common import make_app, run

PORT = 8011


class VerdictRequest(BaseModel):
    claim: str = Field(min_length=1)
    passages: list[str] = Field(default_factory=list)


class VerdictResponse(BaseModel):
    kind: str
    prob: float
    citedEvidence: str | None = None
    claim: str
    rungs_used: list[str]


def _stub_ladder() -> RetrievalLadder:
    from trust.extractors.retrieval_ladder import LadderRung

    return RetrievalLadder(
        [
            LadderRung("hhem-2.1", DeterministicVerdictBackend(floor=0.05), escalate_below=0.7),
            LadderRung("glider-3.8b", DeterministicVerdictBackend(floor=0.1, noise=0.1), escalate_below=0.85),
            LadderRung("lynx-8b", DeterministicVerdictBackend(floor=0.2, noise=0.2), escalate_below=1.01),
        ]
    )


def create_app(ladder: RetrievalLadder | None = None) -> FastAPI:
    from fastapi import FastAPI

    ladder = ladder or _stub_ladder()
    app = make_app("retrieval-verdict")

    @app.post("/verdict", response_model=VerdictResponse)
    def verdict(req: VerdictRequest) -> VerdictResponse:
        v, trace = ladder.verdict(req.claim, req.passages)
        return VerdictResponse(**v.as_dict(), rungs_used=trace.rungs_used)

    return app


app = create_app()


def main() -> None:
    run(app, PORT)
