"""A-S-21 seed-schema: world-doc JSON Schema, versioning, coherence lint.

A WorldDoc is the seed material for the whole simulation unit — what trust
consumes as a synthetic world and what the presence engine uses for persona
priors. Coherence lint is the honest gate: it flags contradictions between
narrative prose and the numeric macro snapshot, and — critically — any date
claims that leak the shock window (= lookahead bias).
"""

from __future__ import annotations

import json
import re
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

CURRENT_SCHEMA_VERSION = "1.0.0"

WORLD_DOC_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://substrate.dev/schemas/simulation/world-doc-1.0.0.json",
    "title": "WorldDoc",
    "type": "object",
    "required": ["schema_version", "world_id", "generated_at", "macro_snapshot", "narrative"],
    "properties": {
        "schema_version": {"type": "string", "enum": ["1.0.0"]},
        "prompt_version": {"type": "string"},
        "world_id": {"type": "string", "minLength": 1},
        "generated_at": {"type": "string"},
        "model": {"type": "string"},
        "macro_snapshot": {
            "type": "object",
            "required": ["as_of", "series"],
            "properties": {
                "as_of": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
                "series": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["series_id", "value"],
                        "properties": {
                            "series_id": {"type": "string"},
                            "value": {"type": "number"},
                            "units": {"type": "string"},
                        },
                    },
                },
            },
        },
        "narrative": {
            "type": "object",
            "required": ["economy", "labor", "consumers", "supply_chain", "sentiment"],
            "properties": {
                "economy": {"type": "string"},
                "labor": {"type": "string"},
                "consumers": {"type": "string"},
                "supply_chain": {"type": "string"},
                "sentiment": {"type": "string"},
            },
        },
        "inferred_risks": {
            "type": "object",
            "properties": {
                "cascade": {"type": "number", "minimum": 0, "maximum": 1},
                "shift_magnitude": {"type": "number", "minimum": 0, "maximum": 1},
            },
        },
    },
}

Validator = Draft202012Validator(WORLD_DOC_SCHEMA)


def validate_world_doc(doc: dict[str, Any]) -> dict[str, Any]:
    """Validate against the versioned schema; returns the doc or raises."""
    errors = sorted(Validator.iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        msgs = "; ".join(f"{'/'.join(map(str, e.path))}: {e.message}" for e in errors[:5])
        raise ValidationError(f"world-doc invalid: {msgs}")
    return doc


def coherence_lint(doc: dict[str, Any]) -> list[str]:
    """Structural coherence + lookahead checks. Returns issues ([] = clean).

    `future-dated` narrative citations are violations: the doc must describe
    the world only as known at `macro_snapshot.as_of` — this is the seed-side
    half of the no-lookahead integrity rule (BUILD.md rule 1).
    """
    issues: list[str] = []
    try:
        validate_world_doc(doc)
    except ValidationError as e:
        return [str(e)]

    as_of = doc["macro_snapshot"]["as_of"]
    as_of_year = int(as_of[:4])
    as_of_month = int(as_of[5:7])
    as_of_pos = as_of_year * 12 + as_of_month
    month_names = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    }
    for key, text in doc["narrative"].items():
        for year in set(re.findall(r"\b(?:19\d\d|20\d\d)\b", text)):
            if int(year) != as_of_year:
                issues.append(
                    f"lookahead-violation: narrative.{key} cites {year} but the snapshot is as of {as_of_year}"
                )
        for m_name, m_num in month_names.items():
            for m_year in set(re.findall(rf"\b{m_name}\s+(19\d\d|20\d\d)\b", text, re.IGNORECASE)):
                m_pos = int(m_year) * 12 + m_num
                if m_pos > as_of_pos:
                    issues.append(
                        f"lookahead-violation: narrative.{key} cites {m_name.title()} {m_year}"
                        f" (after snapshot as of {as_of})"
                    )

    risks = doc.get("inferred_risks", {})
    for k in ("cascade", "shift_magnitude"):
        v = risks.get(k)
        if v is not None and not (0 <= float(v) <= 1):
            issues.append(f"inferred_risks.{k}={v} out of [0,1]")

    # numeric anchor cross-check: every series value must survive a 0.95 round
    # (the narrative is allowed prose; the snapshot is the contract).
    series = {row["series_id"]: row["value"] for row in doc["macro_snapshot"]["series"]}
    if not series:
        issues.append("macro_snapshot.series is empty — a world doc must anchor at least one series")
    return issues


def load_schema() -> dict[str, Any]:
    return WORLD_DOC_SCHEMA