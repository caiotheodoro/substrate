"""A-K-21 source-change-detector — content-hash polling.

Every polled source yields a content hash; a hash that differs from the
ledger's last-seen hash is a `source.changed` change (also published on the
bus when one is attached). CDC is a documented v2 alternative; polling is
the v1 contract.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from substrate_knowledge.m5_freshness.ledger import FreshnessLedger

Fetcher = Callable[[], str]


@dataclass
class Source:
    id: str
    name: str = ""
    kind: str = "path"  # path | uri | callable
    path: str | None = None
    url: str | None = None
    fetch: Fetcher | None = None


@dataclass
class SourceChange:
    source_id: str
    old_hash: str | None
    new_hash: str
    changed_at: float


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class SourceChangeDetector:
    def __init__(self, ledger: FreshnessLedger | None = None, bus: object | None = None) -> None:
        self.ledger = ledger
        self.bus = bus

    def _fetch(self, source: Source) -> str:
        if source.fetch is not None:
            return source.fetch()
        if source.kind == "path" and source.path:
            return Path(source.path).read_text(encoding="utf-8", errors="replace")
        if source.kind == "uri" and source.url:
            import httpx

            resp = httpx.get(source.url, timeout=10.0)
            resp.raise_for_status()
            return resp.text
        raise ValueError(f"source {source.id} has no fetchable content")

    def poll(self, sources: list[Source]) -> list[SourceChange]:
        changes: list[SourceChange] = []
        for source in sources:
            new_hash = content_hash(self._fetch(source))
            old_hash = self.ledger.last_hash(source.id) if self.ledger else None
            if new_hash == old_hash:
                continue
            change = SourceChange(source.id, old_hash, new_hash, time.time())
            changes.append(change)
            if self.ledger is not None:
                self.ledger.record_content_hash(source.id, new_hash)
            if self.bus is not None:
                self.bus.publish("source.changed", {"source_id": source.id, "new_hash": new_hash})
        return changes
