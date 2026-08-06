"""A-T-26 :8034 diversity steering — embeddings + coverage over HTTP."""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from trust.gated_data.diversity import DiversityGate, StubEmbedder
from trust.gated_data.models import SeedRecord
from trust.services._common import make_app, run

PORT = 8034


class SeedModel(BaseModel):
    sample_id: str
    content: str
    label: bool = True
    source: str = "http"


def create_app(gate: DiversityGate | None = None) -> FastAPI:
    gate = gate or DiversityGate(embedder=StubEmbedder())
    app = make_app("diversity")

    @app.post("/gate")
    def run_gate(req: SeedModel) -> dict[str, object]:
        result = gate.evaluate(SeedRecord(req.sample_id, req.content, req.label, req.source))
        return result.as_dict()

    @app.get("/coverage")
    def coverage() -> dict[str, object]:
        return gate.coverage().as_dict()

    return app


app = create_app()


def main() -> None:
    run(app, PORT)
