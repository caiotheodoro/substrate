"""A-T-16 schema-checker — {satisfied, violation_kind}.

JSON Schema satisfaction as the structured-output trust boundary. Violation
kinds are mapped from the jsonschema validator keywords (required -> missing,
type -> type, enum/const -> enum, format -> format, else other).

GBNF note: generation-time GBNF grammars (llama.cpp) can *guarantee* schema
conformance at generation time; this checker remains the enforcement point —
the harness records what was actually emitted, not what was asked for.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ViolationKind = str  # "none" | "missing" | "type" | "enum" | "format" | "other"


@dataclass(frozen=True)
class SchemaCheck:
    satisfied: bool
    violation_kind: ViolationKind = "none"

    def as_dict(self) -> dict[str, Any]:
        return {"satisfied": self.satisfied, "violation_kind": self.violation_kind}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SchemaCheck":
        return cls(satisfied=bool(data["satisfied"]), violation_kind=data.get("violation_kind", "none"))


_VIOLATION_KIND = {"required": "missing", "type": "type", "enum": "enum", "const": "enum", "format": "format"}


def check_schema(value: Any, schema: dict[str, Any]) -> SchemaCheck:
    """Validate ``value`` against ``schema``; a malformed schema is a violation.

    The format checker is enabled (``format`` violations count — jsonschema
    ignores them by default otherwise)."""
    try:
        import jsonschema
        from jsonschema import FormatChecker
    except ImportError:  # pragma: no cover
        raise RuntimeError("jsonschema not installed")
    validator_cls = jsonschema.validators.validator_for(schema)
    try:
        validator_cls.check_schema(schema)
        validator = validator_cls(schema, format_checker=FormatChecker())
        validator.validate(value)
        return SchemaCheck(True, "none")
    except jsonschema.exceptions.SchemaError:
        return SchemaCheck(False, "other")
    except (jsonschema.exceptions.ValidationError, TypeError) as err:
        kind = _VIOLATION_KIND.get(getattr(err, "validator", None) or "", "other")
        return SchemaCheck(False, kind)
