"""A-T-22 :8030 data-ingest — seeds in, provenance-stamped SeedRecords out."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from trust.gated_data.ingest import StaticWorldSeedSource, stamp_provenance
from trust.gated_data.models import SeedRecord
from trust.services._common import make_app, run

PORT = 8030


class IngestRequest(BaseModel):
    source: str = "static"
    rows: list[dict[str, Any]] = Field(default_factory=list)


class SeedModel(BaseModel):
    sample_id: str
    content: str
    label: bool
    source: str
    world: str
    provenance: dict[str, str]


def create_app() -> FastAPI:
    app = make_app("data-ingest")
    ingested: dict[str, SeedModel] = {}

    @app.post("/ingest", response_model=list[SeedModel])
    def ingest(req: IngestRequest) -> list[SeedModel]:
        seeds: list[SeedRecord] = []
        if req.rows:
            seeds = [
                SeedRecord(
                    sample_id=r["sample_id"],
                    content=r["content"],
                    label=bool(r["label"]),
                    source=r.get("source", req.source),
                    world=r.get("world", "world-unknown"),
                    metadata=r.get("metadata", {}),
                    signal_kinds=r.get("signal_kinds", []),
                )
                for r in req.rows
            ]
        else:
            seeds = StaticWorldSeedSource().fetch_seeds()
        out: list[SeedModel] = []
        for s in seeds:
            stamp = stamp_provenance(s)
            model = SeedModel(
                sample_id=s.sample_id,
                content=s.content,
                label=s.label,
                source=s.source,
                world=s.world,
                provenance=stamp,
            )
            ingested[s.sample_id] = model
            out.append(model)
        return out

    @app.get("/seeds")
    def list_seeds() -> list[SeedModel]:
        return list(ingested.values())

    return app


app = create_app()


def main() -> None:
    run(app, PORT)
