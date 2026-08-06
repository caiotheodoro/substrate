"""A-T-25 :8033 contamination gate — MinHash LSH + n-gram vs holdout, with quarantine."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from trust.gated_data.contamination import ContaminationGate, InMemoryQuarantineStore
from trust.gated_data.models import SeedRecord
from trust.services._common import make_app, run

PORT = 8033


class CheckRequest(BaseModel):
    sample_id: str
    content: str
    label: bool = True
    source: str = "http"


def create_app(gate: ContaminationGate | None = None) -> FastAPI:
    quarantine = InMemoryQuarantineStore()
    gate = gate or ContaminationGate(quarantine=quarantine)
    app = make_app("contamination")

    @app.post("/check")
    def check(req: CheckRequest) -> dict[str, Any]:
        result = gate.evaluate(SeedRecord(req.sample_id, req.content, req.label, req.source))
        return result.as_dict()

    @app.get("/quarantine")
    def list_quarantine() -> dict[str, Any]:
        return {"count": len(quarantine.list()), "reasons": quarantine.reasons()}

    return app


app = create_app()


def main() -> None:
    run(app, PORT)
