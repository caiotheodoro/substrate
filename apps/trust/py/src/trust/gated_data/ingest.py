"""A-T-22 data-ingest — seeds from 05's synthetic worlds (C6, HTTP-stubbed)
or static local JSON, with provenance stamping at the moment of ingestion.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from trust.gated_data.models import SeedRecord


class WorldSeedSource(Protocol):
    """05's worlds API (``C6`` via ``:8300``) behind a protocol; the compose
    service uses the HTTP client, tests use static sources."""

    kind: str

    def fetch_seeds(self) -> list[SeedRecord]: ...


class StaticWorldSeedSource:
    """Local JSON / inline seeds — the offline stand-in for 05's worlds."""

    kind = "static"

    def __init__(self, seeds: list[SeedRecord] | None = None, path: str | None = None) -> None:
        self._seeds = seeds or []
        if path:
            self._seeds = self._from_jsonl(path)

    @staticmethod
    def _from_jsonl(path: str) -> list[SeedRecord]:
        rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
        return [
            SeedRecord(
                sample_id=r["sample_id"],
                content=r["content"],
                label=bool(r["label"]),
                source=r.get("source", "static"),
                world=r.get("world", "world-unknown"),
                metadata=r.get("metadata", {}),
                signal_kinds=r.get("signal_kinds", []),
            )
            for r in rows
        ]

    def fetch_seeds(self) -> list[SeedRecord]:
        return list(self._seeds)


class HttpWorldSeedSource:
    """05's sim-api (``http://localhost:8300``) — cross-unit import per the
    port map. Never required by tests; construct only when 05 is up."""

    kind = "http"

    def __init__(self, base_url: str = "http://localhost:8300") -> None:
        self.base_url = base_url

    def fetch_seeds(self) -> list[SeedRecord]:
        import httpx

        resp = httpx.get(f"{self.base_url}/worlds/seeds", timeout=30)
        resp.raise_for_status()
        rows = resp.json()
        return [
            SeedRecord(
                sample_id=str(r["id"]),
                content=r["content"],
                label=bool(r.get("label", True)),
                source=r.get("source", "simulation"),
                world=r.get("world", "world-unknown"),
                metadata=r,
            )
            for r in rows
        ]


def stamp_provenance(seed: SeedRecord, ingested_by: str = "trust-ingest") -> dict[str, str]:
    """A-T-22 provenance stamp: when, from where, and who ingested the seed."""
    return {
        "seed_id": seed.sample_id,
        "source": seed.source,
        "world": seed.world,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "ingested_by": ingested_by,
        "content_sha256": _sha256(seed.content),
    }


def _sha256(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode()).hexdigest()
