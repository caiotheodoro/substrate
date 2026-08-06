"""A-T-27 provenance-tracker — per-sample lineage: source → gates → dataset
version. Every event is append-only and serializable; the dataset manifest
references the tracker's records.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol


@dataclass
class ProvenanceEvent:
    stage: str
    detail: dict[str, Any] = field(default_factory=dict)
    at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def as_dict(self) -> dict[str, Any]:
        return {"stage": self.stage, "detail": self.detail, "at": self.at}


@dataclass
class ProvenanceRecord:
    """Lineage of one sample: source world, seed identity, gate outcomes."""

    sample_id: str
    source: str
    world: str
    seed_id: str
    events: list[ProvenanceEvent] = field(default_factory=list)
    dataset_version: str | None = None

    def add(self, stage: str, detail: dict[str, Any] | None = None) -> None:
        self.events.append(ProvenanceEvent(stage, detail or {}))

    def as_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "source": self.source,
            "world": self.world,
            "seed_id": self.seed_id,
            "dataset_version": self.dataset_version,
            "events": [e.as_dict() for e in self.events],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProvenanceRecord":
        rec = cls(
            sample_id=data["sample_id"],
            source=data.get("source", ""),
            world=data.get("world", ""),
            seed_id=data.get("seed_id", ""),
            dataset_version=data.get("dataset_version"),
        )
        rec.events = [ProvenanceEvent(e["stage"], e.get("detail", {}), e.get("at", "")) for e in data.get("events", [])]
        return rec


class ProvenanceTracker(Protocol):
    def record(self, sample_id: str) -> ProvenanceRecord: ...
    def get(self, sample_id: str) -> ProvenanceRecord | None: ...
    def all(self) -> list[ProvenanceRecord]: ...


class InMemoryProvenanceTracker:
    """Append-only lineage store (Postgres-backed ``provenance`` table in
    compose; in-memory here so the library is self-contained)."""

    def __init__(self) -> None:
        self._records: dict[str, ProvenanceRecord] = {}

    def record(self, sample_id: str) -> ProvenanceRecord:
        if sample_id not in self._records:
            self._records[sample_id] = ProvenanceRecord(sample_id=sample_id, source="", world="", seed_id="")
        return self._records[sample_id]

    def get(self, sample_id: str) -> ProvenanceRecord | None:
        return self._records.get(sample_id)

    def all(self) -> list[ProvenanceRecord]:
        return list(self._records.values())
