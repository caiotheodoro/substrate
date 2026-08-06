"""A-K-27 verdict-store — verdict history and support rate.

Feeds 02 (support/contradiction/silent per retrieval) and 01 (event log).
Backed by the generic KV Store: in-memory for tests, Postgres under compose.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from substrate_knowledge.core.storage import Store
from substrate_knowledge.core.verdicts import RetrievalVerdict, VerdictKind


class VerdictStore:
    def __init__(self, store: Store) -> None:
        self.store = store

    def record(self, verdict: RetrievalVerdict, *, source: str = "gate", query: str = "") -> str:
        verdict_id = f"verdict:{uuid.uuid4().hex[:12]}"
        self.store.put(
            verdict_id,
            {
                "kind": verdict.kind.value,
                "prob": verdict.prob,
                "citedEvidence": verdict.citedEvidence,
                "claim": verdict.claim,
                "source": source,
                "query": query,
                "ts": time.time(),
            },
        )
        return verdict_id

    def history(self, claim: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        rows = [value for _, value in self.store.scan("verdict:")]
        if claim is not None:
            rows = [r for r in rows if r["claim"] == claim]
        rows.sort(key=lambda r: r.get("ts", 0), reverse=True)
        return rows[:limit]

    def counts(self, source: str | None = None) -> dict[str, int]:
        counts = {"support": 0, "contradict": 0, "silent": 0}
        for _, value in self.store.scan("verdict:"):
            if source is not None and value.get("source") != source:
                continue
            kind = value.get("kind")
            if kind in counts:
                counts[kind] += 1
        return counts

    def support_rate(self, source: str | None = None) -> float | None:
        counts = self.counts(source)
        total = sum(counts.values())
        if total == 0:
            return None
        return counts["support"] / total

    def contradict_rate(self, source: str | None = None) -> float | None:
        counts = self.counts(source)
        total = sum(counts.values())
        if total == 0:
            return None
        return counts["contradict"] / total

    def n_verdicts(self) -> int:
        return self.store.count("verdict:")
