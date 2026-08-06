"""A-T-24 :8032 label-quality gate (v1-lite) — sampling + in-memory review queue."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from trust.gated_data.label_quality import LabelQualityGate, ReviewItem
from trust.gated_data.models import SeedRecord
from trust.services._common import make_app, run

PORT = 8032


class SeedModel(BaseModel):
    sample_id: str
    content: str
    label: bool = True
    source: str = "http"


class ReviewResolve(BaseModel):
    sample_id: str
    decision: bool
    reviewer: str = "human"


def create_app(gate: LabelQualityGate | None = None) -> FastAPI:
    gate = gate or LabelQualityGate()
    app = make_app("label-quality")

    @app.post("/gate")
    def run_gate(req: SeedModel) -> dict[str, Any]:
        result = gate.evaluate(SeedRecord(req.sample_id, req.content, req.label, req.source))
        return result.as_dict()

    @app.get("/queue")
    def queue() -> list[dict[str, object]]:
        return [i.as_dict() for i in gate.queue.pending()]

    @app.post("/review")
    def review(req: ReviewResolve) -> dict[str, Any]:
        gate.queue.resolve(req.sample_id, req.decision, req.reviewer)
        return {"sample_id": req.sample_id, "decision": req.decision}

    return app


app = create_app()


def main() -> None:
    run(app, PORT)
