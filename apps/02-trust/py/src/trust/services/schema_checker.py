"""A-T-16 :8012 schema-checker — {satisfied, violation_kind} over HTTP."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from trust.extractors.schema_checker import check_schema
from trust.services._common import make_app, run

PORT = 8012


class SchemaCheckRequest(BaseModel):
    value: Any
    schema: dict[str, Any]


class SchemaCheckResponse(BaseModel):
    satisfied: bool
    violation_kind: str


def create_app() -> FastAPI:
    app = make_app("schema-checker")

    @app.post("/check", response_model=SchemaCheckResponse)
    def check(req: SchemaCheckRequest) -> SchemaCheckResponse:
        return SchemaCheckResponse(**check_schema(req.value, req.schema).as_dict())

    return app


app = create_app()


def main() -> None:
    run(app, PORT)
