"""A-T-14 :8010 tool-call verifier — zero-LLM by construction."""
from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

from trust.extractors.tool_call_verifier import ToolCallRecord, ToolCallVerdict, verify_tool_call
from trust.services._common import make_app, run

PORT = 8010


class ToolCallModel(BaseModel):
    call_id: str = Field(min_length=1)
    tool_name: str
    status: Literal["success", "error"]
    result: Any = None
    expected_sign: Literal["positive", "negative", "zero", "any"] = "any"
    result_schema: Optional[dict[str, Any]] = None
    error_message: str | None = None


class ToolCallVerdictModel(BaseModel):
    ran: bool
    result_sign: bool
    error: bool
    result_schema_ok: bool


def create_app() -> FastAPI:
    app = make_app("tool-call-verifier")

    @app.post("/verify", response_model=ToolCallVerdictModel)
    def verify(req: ToolCallModel) -> ToolCallVerdictModel:
        verdict = verify_tool_call(
            ToolCallRecord(
                call_id=req.call_id,
                tool_name=req.tool_name,
                status=req.status,
                result=req.result,
                expected_sign=req.expected_sign,
                result_schema=req.result_schema,
                error_message=req.error_message,
            )
        )
        return ToolCallVerdictModel(**verdict.as_dict())

    return app


app = create_app()


def main() -> None:
    run(app, PORT)
