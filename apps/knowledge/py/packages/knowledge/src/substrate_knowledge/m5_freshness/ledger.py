"""A-K-24 freshness-ledger.

Per-source: last-ingested timestamp, content hash, staleness age, trigger
history, cumulative re-ingest cost. Backed by the generic KV Store
(in-memory for tests, Postgres under compose).
"""

from __future__ import annotations

import time
from typing import Any

from substrate_knowledge.core.storage import Store


class FreshnessLedger:
    def __init__(self, store: Store) -> None:
        self.store = store

    # ------------------------------------------------------------------
    def record_ingestion(self, source_id: str, *, ts: float | None = None, cost: float = 0.0, doc_count: int = 0) -> None:
        entry = self.store.get(f"fresh:last:{source_id}") or {
            "source_id": source_id,
            "last_ingested": None,
            "last_hash": None,
            "cost_total": 0.0,
            "doc_count_total": 0,
        }
        ts = ts or time.time()
        entry["last_ingested"] = ts
        entry["cost_total"] = float(entry.get("cost_total", 0.0)) + cost
        entry["doc_count_total"] = int(entry.get("doc_count_total", 0)) + doc_count
        self.store.put(f"fresh:last:{source_id}", entry)

    def record_content_hash(self, source_id: str, content_hash: str) -> None:
        entry = self.store.get(f"fresh:last:{source_id}") or {"source_id": source_id}
        entry["last_hash"] = content_hash
        self.store.put(f"fresh:last:{source_id}", entry)

    def record_trigger(self, source_id: str, reason: str) -> None:
        key = f"fresh:trigger:{source_id}:{int(time.time() * 1000)}"
        self.store.put(key, {"source_id": source_id, "reason": reason, "ts": time.time()})

    # ------------------------------------------------------------------
    def last_ingested(self, source_id: str) -> float | None:
        entry = self.store.get(f"fresh:last:{source_id}")
        return entry.get("last_ingested") if entry else None

    def last_hash(self, source_id: str) -> str | None:
        entry = self.store.get(f"fresh:last:{source_id}")
        return entry.get("last_hash") if entry else None

    def staleness_age(self, source_id: str, now: float | None = None) -> float | None:
        """Age in seconds since last ingestion; None when never ingested."""
        last = self.last_ingested(source_id)
        if last is None:
            return None
        return (now or time.time()) - last

    def is_stale(self, source_id: str, max_age_s: float, now: float | None = None) -> bool:
        age = self.staleness_age(source_id, now=now)
        return age is None or age > max_age_s

    def trigger_history(self, source_id: str) -> list[dict[str, Any]]:
        return [value for _, value in self.store.scan(f"fresh:trigger:{source_id}:")]

    def cost_total(self, source_id: str) -> float:
        entry = self.store.get(f"fresh:last:{source_id}")
        return float(entry.get("cost_total", 0.0)) if entry else 0.0

    def sources(self) -> list[str]:
        return sorted({key.split(":", 2)[2] for key, _ in self.store.scan("fresh:last:") if len(key.split(":", 2)) == 3})
