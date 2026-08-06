"""A-T-14 tool-call-verifier — {ran, result_sign, error, result_schema_ok}.

Zero-LLM by construction: the tool returned, so the record is a fact about the
world. ``result_schema_ok`` is enforced with JSON Schema via ``jsonschema``;
``result_sign`` compares the first numeric value of the result against an
expected sign (positive / negative / zero / any).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

SignExpectation = Literal["positive", "negative", "zero", "any"]


@dataclass(frozen=True)
class ToolCallVerdict:
    """The verifier's output — one row of the A-T-14 feature group."""

    ran: bool
    result_sign: bool
    error: bool
    result_schema_ok: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "ran": self.ran,
            "result_sign": self.result_sign,
            "error": self.error,
            "result_schema_ok": self.result_schema_ok,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolCallVerdict":
        return cls(
            ran=bool(data["ran"]),
            result_sign=bool(data["result_sign"]),
            error=bool(data["error"]),
            result_schema_ok=bool(data["result_schema_ok"]),
        )


@dataclass(frozen=True)
class ToolCallRecord:
    """The raw record a harness hands us after invoking a tool."""

    call_id: str
    tool_name: str
    status: Literal["success", "error"]
    result: Any = None
    expected_sign: SignExpectation = "any"
    result_schema: Optional[dict[str, Any]] = None
    error_message: str | None = None


def _first_numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    if isinstance(value, dict):
        for v in value.values():
            hit = _first_numeric(v)
            if hit is not None:
                return hit
    if isinstance(value, (list, tuple)):
        for v in value:
            hit = _first_numeric(v)
            if hit is not None:
                return hit
    return None


def _sign_of(value: float) -> str:
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "zero"


def verify_tool_call(record: ToolCallRecord) -> ToolCallVerdict:
    """Produce {ran, result_sign, error, result_schema_ok} for a tool call.

    - ``ran``: the call returned a result (or completed) — the action happened.
    - ``error``: the call raised / reported an error.
    - ``result_sign``: first numeric value of the result matches ``expected_sign``
      (``any`` always passes; a non-numeric result fails the sign check).
    - ``result_schema_ok``: result satisfies ``result_schema``; a missing schema
      is vacuously satisfied; an invalid schema counts as a violation.
    """
    ran = record.status == "success" or record.result is not None
    error = record.status == "error" or record.error_message is not None

    sign_ok = True
    numeric = _first_numeric(record.result)
    if numeric is None:
        sign_ok = False
    elif record.expected_sign != "any":
        sign_ok = _sign_of(numeric) == record.expected_sign

    schema_ok = True
    if record.result_schema is not None:
        schema_ok = _satisfies_schema(record.result, record.result_schema)

    return ToolCallVerdict(ran=ran, result_sign=sign_ok, error=error, result_schema_ok=schema_ok)


def _satisfies_schema(value: Any, schema: dict[str, Any]) -> bool:
    try:
        import jsonschema
        from jsonschema import FormatChecker
    except ImportError:  # pragma: no cover
        raise RuntimeError("jsonschema not installed")
    try:
        validator_cls = jsonschema.validators.validator_for(schema)
        validator_cls.check_schema(schema)
        validator = validator_cls(schema, format_checker=FormatChecker())
        validator.validate(value)
        return True
    except (jsonschema.exceptions.ValidationError, jsonschema.exceptions.SchemaError, TypeError):
        return False
