"""A-T-31 outcome-reconciler — pending / confirmed / delayed / conflicting,
with a staleness TTL.

State machine over a C2 row (``arrived_at`` = when this unit consumed the row
from 01's log — the C2 contract carries no creation timestamp, so arrival
time is the local clock reference):

- ``pending``     outcome is None, age < TTL
- ``delayed``     outcome is None, age >= TTL (staleness — the loop can't
                  wait forever; delayed rows still count for retraining with
                  the drift the band report surfaces)
- ``confirmed``   outcome set AND ``confirmedAt`` set
- ``conflicting`` outcome set but ``confirmedAt`` missing (data-integrity
                  conflict), or the outcome contradicts the gate's intent
                  (reject/escalate yet later confirmed true)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from trust.contracts import DecisionRecord

ReconciliationState = Literal["pending", "confirmed", "delayed", "conflicting"]


@dataclass(frozen=True)
class Reconciliation:
    state: ReconciliationState
    reason: str
    age_seconds: float = 0.0

    def as_dict(self) -> dict[str, object]:
        return {"state": self.state, "reason": self.reason, "age_seconds": round(self.age_seconds, 1)}


def _parse_iso(ts: str) -> datetime:
    parsed = datetime.fromisoformat(ts)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class OutcomeReconciler:
    """A-T-31. ``now`` is injectable for deterministic tests."""

    def __init__(self, staleness_ttl_seconds: float = 86400.0) -> None:
        self.staleness_ttl_seconds = staleness_ttl_seconds

    @staticmethod
    def _age_seconds(arrived_at: str | None, now: str | None) -> float:
        if arrived_at is None:
            return 0.0
        reference = _parse_iso(now) if now else datetime.now(timezone.utc)
        return (reference - _parse_iso(arrived_at)).total_seconds()

    def reconcile(self, record: DecisionRecord, now: str | None = None, arrived_at: str | None = None) -> Reconciliation:
        if record.outcome is not None:
            if record.confirmedAt is None:
                return Reconciliation("conflicting", "outcome set without confirmedAt")
            if record.verdict == "reject" and record.outcome is True:
                return Reconciliation("conflicting", "rejected decision later confirmed true")
            if record.verdict == "escalate" and record.outcome is True:
                return Reconciliation("conflicting", "escalated decision confirmed true")
            return Reconciliation("confirmed", "outcome confirmed")
        age = self._age_seconds(arrived_at, now)
        if age >= self.staleness_ttl_seconds:
            return Reconciliation("delayed", "outcome not confirmed within TTL", age)
        return Reconciliation("pending", "awaiting outcome", age)

    def reconcile_many(
        self,
        records: list[DecisionRecord],
        now: str | None = None,
        arrived_at: str | None = None,
    ) -> dict[ReconciliationState, int]:
        counts: dict[ReconciliationState, int] = {"pending": 0, "confirmed": 0, "delayed": 0, "conflicting": 0}
        for record in records:
            counts[self.reconcile(record, now, arrived_at).state] += 1
        return counts
