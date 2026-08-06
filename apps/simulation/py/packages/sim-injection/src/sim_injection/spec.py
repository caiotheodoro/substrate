"""A-S-23 injection-spec: Shock{profile, magnitude, channels, start} schema.

Mirrors the C6 ShockInterventionSchema shape (packages/substrate) plus a
ramp for replayable interventions; the schema is the wire contract reused by
01's stress-testing via sim-api :8300.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

SHOCK_SPEC_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://substrate.dev/schemas/simulation/shock-spec-1.0.0.json",
    "title": "ShockSpec",
    "type": "object",
    "required": ["id", "profile", "magnitude", "channels", "start"],
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "profile": {"type": "string", "enum": [
            "supply-demand shift", "logistics capacity shock", "monetary tightening",
            "trade-policy shock", "sentiment cascade",
        ]},
        "magnitude": {"type": "number", "minimum": -2, "maximum": 2},
        "channels": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "start": {"type": "string", "pattern": "^\\d{4}-\\d{2}"},
        "ramp": {"type": "string", "enum": ["step", "linear", "exponential"], "default": "step"},
        "horizon": {"type": "integer", "minimum": 1, "default": 12},
        "seed": {"type": "string"},
    },
}

_SpecValidator = Draft202012Validator(SHOCK_SPEC_SCHEMA)


def validate_shock_spec(spec: dict[str, Any]) -> dict[str, Any]:
    errors = sorted(_SpecValidator.iter_errors(spec), key=lambda e: list(e.path))
    if errors:
        msgs = "; ".join(f"{'/'.join(map(str, e.path))}: {e.message}" for e in errors[:5])
        raise ValidationError(f"shock-spec invalid: {msgs}")
    return spec


@dataclass
class InjectionSpec:
    id: str
    profile: str
    magnitude: float
    channels: list[str]
    start: str
    ramp: str = "step"
    horizon: int = 12
    seed: str = "1.0.0"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "profile": self.profile,
            "magnitude": self.magnitude,
            "channels": self.channels,
            "start": self.start,
            "ramp": self.ramp,
            "horizon": self.horizon,
            "seed": self.seed,
        }

    @classmethod
    def from_dict(cls, spec: dict[str, Any]) -> "InjectionSpec":
        validate_shock_spec(spec)
        return cls(
            id=spec["id"],
            profile=spec["profile"],
            magnitude=float(spec["magnitude"]),
            channels=list(spec["channels"]),
            start=spec["start"],
            ramp=spec.get("ramp", "step"),
            horizon=int(spec.get("horizon", 12)),
            seed=spec.get("seed", "1.0.0"),
        )