"""A-T-23 :8031 verifiability gate — per-seed checkable-and-true over HTTP."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from trust.gated_data.models import SeedRecord
from trust.gated_data.verifiability import VerifiabilityGate
from trust.services._common import make_app, run

PORT = 8031


class SeedModel(BaseModel):
    sample_id: str
    content: str
    label: bool = True
    source: str = "http"
    world: str = "world-unknown"
    metadata: dict[str, Any] = {}
    signal_kinds: list[str] = []


class GateResponse(BaseModel):
    gate: str
    passed: bool
    reason: str
    detail: dict[str, Any] = {}


def create_app(gate: VerifiabilityGate | None = None) -> FastAPI:
    gate = gate or VerifiabilityGate()
    app = make_app("verifiability")

    @app.post("/gate", response_model=GateResponse)
    def run_gate(req: SeedModel) -> GateResponse:
        result = gate.evaluate(
            SeedRecord(
                sample_id=req.sample_id,
                content=req.content,
                label=req.label,
                source=req.source,
                world=req.world,
                metadata=req.metadata,
                signal_kinds=req.signal_kinds,
            )
        )
        return GateResponse(**result.as_dict())

    return app


app = create_app()


def main() -> None:
    run(app, PORT)
