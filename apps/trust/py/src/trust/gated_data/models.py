"""A-T-28 data models for the gated pipeline — SeedRecord, GatePolicy,
GatedSample, Dataset. The public API of ``trust.gated_data``.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from trust.gated_data.provenance import ProvenanceRecord


@dataclass
class SeedRecord:
    """One raw candidate sample from a world source (A-T-22)."""

    sample_id: str
    content: str
    label: bool
    source: str
    world: str = "world-unknown"
    metadata: dict[str, Any] = field(default_factory=dict)
    signal_kinds: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "content": self.content,
            "label": self.label,
            "source": self.source,
            "world": self.world,
            "metadata": self.metadata,
            "signal_kinds": self.signal_kinds,
        }


@dataclass
class GateVerdictResult:
    gate: str
    passed: bool
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"gate": self.gate, "passed": self.passed, "reason": self.reason, "detail": self.detail}


@dataclass
class GatedSample:
    """A sample that cleared every gate, with full lineage (A-T-27)."""

    sample_id: str
    content: str
    label: bool
    provenance: ProvenanceRecord
    gate_results: list[GateVerdictResult] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "content": self.content,
            "label": self.label,
            "provenance": self.provenance.as_dict(),
            "gate_results": [g.as_dict() for g in self.gate_results],
        }


@dataclass
class GatePolicy:
    """The A-T-28 policy — every gate is configurable and off-able."""

    verifiability: bool = True
    require_checkable: bool = True
    require_verified: bool = True
    label_quality: bool = True
    label_sample_rate: float = 0.5
    contamination: bool = True
    minhash_threshold: float = 0.6
    ngram_threshold: float = 0.4
    ngram_n: int = 5
    diversity: bool = True
    diversity_distance_threshold: float = 0.3
    quarantine_contaminated: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "verifiability": self.verifiability,
            "require_checkable": self.require_checkable,
            "require_verified": self.require_verified,
            "label_quality": self.label_quality,
            "label_sample_rate": self.label_sample_rate,
            "contamination": self.contamination,
            "minhash_threshold": self.minhash_threshold,
            "ngram_threshold": self.ngram_threshold,
            "diversity": self.diversity,
            "quarantine_contaminated": self.quarantine_contaminated,
        }


@dataclass
class DatasetSummary:
    total: int
    accepted: int
    rejected: int
    rejected_by_gate: dict[str, int] = field(default_factory=dict)
    quarantine_reasons: Counter = field(default_factory=Counter)
    diversity_coverage: float = 0.0
    version: str = "v1"

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "rejected_by_gate": self.rejected_by_gate,
            "quarantine_reasons": dict(self.quarantine_reasons),
            "diversity_coverage": round(self.diversity_coverage, 4),
            "version": self.version,
        }


@dataclass
class Dataset:
    """THE deliverable (A-T-28): ``gate(seeds, policy) -> Dataset``."""

    version: str
    samples: list[GatedSample]
    provenance: dict[str, ProvenanceRecord] = field(default_factory=dict)
    summary: Optional[DatasetSummary] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_jsonl(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as fh:
            for s in self.samples:
                fh.write(json.dumps(s.as_dict()) + "\n")
        return path

    @classmethod
    def from_jsonl(cls, path: str | Path) -> "Dataset":
        rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
        samples = [
            GatedSample(
                sample_id=r["sample_id"],
                content=r["content"],
                label=r["label"],
                provenance=ProvenanceRecord.from_dict(r["provenance"]),
                gate_results=[GateVerdictResult(**g) for g in r.get("gate_results", [])],
            )
            for r in rows
        ]
        return cls(version="v1", samples=samples)

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "created_at": self.created_at,
            "summary": self.summary.as_dict() if self.summary else None,
            "samples": [s.as_dict() for s in self.samples],
        }

    def write_manifest(self, path: str | Path) -> Path:
        path = Path(path)
        payload = {"version": self.version, "created_at": self.created_at, "summary": self.summary.as_dict() if self.summary else None}
        path.write_text(json.dumps(payload, indent=2))
        return path
