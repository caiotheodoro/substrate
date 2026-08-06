"""A-K-23 re-ingestion-scheduler.

APScheduler is the production scheduler; `trigger()` is the pure function
tests and CLI call directly: it records the trigger in the ledger, publishes
`source.changed` on the bus, and (when the apscheduler backend is live)
registers a one-shot job. The scheduler degrades to manual triggering when
APScheduler is unavailable.
"""

from __future__ import annotations

import time
from typing import Any

from substrate_knowledge.m5_freshness.ledger import FreshnessLedger


class ReingestionScheduler:
    def __init__(self, ledger: FreshnessLedger, bus: object | None = None, backend: str = "manual") -> None:
        self.ledger = ledger
        self.bus = bus
        self.backend = backend
        self._scheduler: Any | None = None
        self._jobs: dict[str, str] = {}
        if backend == "apscheduler":
            self._init_apscheduler()

    def _init_apscheduler(self) -> None:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler

            self._scheduler = BackgroundScheduler()
            self._scheduler.start()
        except Exception:
            self._scheduler = None

    def trigger(self, source_id: str, *, reason: str = "manual") -> str:
        """Record + publish + schedule. Returns the trigger key."""
        self.ledger.record_trigger(source_id, reason)
        if self.bus is not None:
            self.bus.publish("source.changed", {"source_id": source_id, "reason": reason})
        key = f"trigger:{source_id}:{time.time():.6f}"
        if self._scheduler is not None:
            self._jobs[source_id] = str(
                self._scheduler.add_job(self._reingest_job, "date", run_date=None, args=[source_id])
            )
        return key

    def _reingest_job(self, source_id: str) -> None:
        self.ledger.record_ingestion(source_id)

    def schedule(self, source_id: str, *, delay_s: float = 0.0, reason: str = "scheduled") -> str:
        key = self.trigger(source_id, reason=reason)
        if delay_s > 0 and self._scheduler is not None:
            self._jobs[source_id] = str(
                self._scheduler.add_job(self._reingest_job, "date", run_date=None, args=[source_id])
            )
        return key

    def shutdown(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
