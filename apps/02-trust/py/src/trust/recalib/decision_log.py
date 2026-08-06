"""A-T-30 decision-log-consumer — polls 01's decision log for C2 rows.

Cross-unit import per the port map: 01 exposes the log over ``:8930``
(REST) / ``:8934`` (gate); the HTTP source is the production client. Tests
use the in-memory fake — nothing here requires 01 to be running.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from trust.contracts import DecisionRecord
from trust.db import InMemoryDecisionLogStore


class DecisionLogSource(Protocol):
    """Cursor-based feed of C2 rows. ``fetch_since`` returns (rows, next cursor)."""

    kind: str

    def fetch_since(self, cursor: str | None, limit: int = 1000) -> tuple[list[DecisionRecord], str]: ...


class HttpDecisionLogSource:
    """Polls 01's decision log API (``http://localhost:8930/decisions``)."""

    kind = "http"

    def __init__(self, base_url: str = "http://localhost:8930") -> None:
        self.base_url = base_url

    def fetch_since(self, cursor: str | None, limit: int = 1000) -> tuple[list[DecisionRecord], str]:
        import httpx

        params = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        resp = httpx.get(f"{self.base_url}/decisions", params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        rows = [DecisionRecord(**r) for r in data.get("rows", [])]
        return rows, data.get("nextCursor", rows[-1].decisionId if rows else cursor)


class InMemoryDecisionLogSource:
    """Deterministic fake of 01's log feed for offline tests."""

    kind = "inmem"

    def __init__(self, rows: list[DecisionRecord] | None = None) -> None:
        self._store = InMemoryDecisionLogStore()
        for r in rows or []:
            self._store.add(r)

    def fetch_since(self, cursor: str | None, limit: int = 1000) -> tuple[list[DecisionRecord], str]:
        return self._store.fetch_since(cursor, limit)


@dataclass
class OutcomeStore:
    """Local labeled-features/outcomes mirror of the decision log (the raw
    material for A-T-18 retraining and the A-T-31 reconciler)."""

    records: list[DecisionRecord] = field(default_factory=list)

    def add(self, record: DecisionRecord) -> None:
        if any(r.decisionId == record.decisionId for r in self.records):
            raise ValueError(f"duplicate decisionId: {record.decisionId}")
        self.records.append(record)

    def labeled(self) -> list[DecisionRecord]:
        return [r for r in self.records if r.outcome is not None]

    def training_frame(self) -> tuple[list[dict[str, float]], list[bool]]:
        """(features, outcomes) for scorer-train — only confirmed outcomes."""
        labeled = self.labeled()
        features = [{k: float(v) if isinstance(v, (int, float)) else float(v == True) for k, v in r.confidenceFeatures.items()} for r in labeled]
        labels = [bool(r.outcome) for r in labeled]
        return features, labels


class DecisionLogConsumer:
    """Polls a source on demand (``poll_once``) and stores C2 rows locally."""

    def __init__(self, source: DecisionLogSource, store: OutcomeStore | None = None) -> None:
        self.source = source
        self.store = store or OutcomeStore()
        self._cursor: str | None = None

    def poll_once(self, limit: int = 1000) -> int:
        rows, next_cursor = self.source.fetch_since(self._cursor, limit)
        consumed = 0
        for row in rows:
            try:
                self.store.add(row)
                consumed += 1
            except ValueError:
                continue
        self._cursor = next_cursor or self._cursor
        return consumed
