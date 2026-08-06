"""A-K-14 human-confirmation-queue.

Merge / split / skip with audit. Only pairs that land in the ambiguity band
(A-K-13) ever reach a human — the Harness escalation philosophy: humans
only on the uncertain edge. Backed by the generic KV Store.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal

from substrate_knowledge.core.storage import Store

Resolution = Literal["merge", "split", "skip"]


class QueueItem:
    def __init__(self, item_id: str, left: dict[str, Any], right: dict[str, Any], score: float, ts: float) -> None:
        self.id = item_id
        self.left = left
        self.right = right
        self.score = score
        self.ts = ts
        self.status = "pending"
        self.resolution: Resolution | None = None
        self.audited_by: str | None = None
        self.audited_at: float | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "left": self.left,
            "right": self.right,
            "score": round(self.score, 4),
            "ts": self.ts,
            "status": self.status,
            "resolution": self.resolution,
            "audited_by": self.audited_by,
            "audited_at": self.audited_at,
        }


class HumanConfirmationQueue:
    def __init__(self, store: Store) -> None:
        self.store = store

    def enqueue(self, left: dict[str, Any], right: dict[str, Any], score: float) -> QueueItem:
        item_id = f"q:{uuid.uuid4().hex[:12]}"
        item = QueueItem(item_id, left, right, score, time.time())
        self.store.put(item_id, item.to_dict())
        return item

    def pending(self) -> list[QueueItem]:
        return [self._from_dict(item_id, value) for item_id, value in self.store.scan("q:") if value["status"] == "pending"]

    def get(self, item_id: str) -> QueueItem | None:
        value = self.store.get(item_id)
        return self._from_dict(item_id, value) if value else None

    def resolve(self, item_id: str, resolution: Resolution, audited_by: str = "human") -> QueueItem:
        value = self.store.get(item_id)
        if value is None:
            raise KeyError(f"unknown queue item {item_id}")
        if resolution not in ("merge", "split", "skip"):
            raise ValueError(f"resolution must be merge|split|skip, got {resolution!r}")
        value["status"] = "resolved"
        value["resolution"] = resolution
        value["audited_by"] = audited_by
        value["audited_at"] = time.time()
        self.store.put(item_id, value)
        audit_id = f"queue:audit:{uuid.uuid4().hex[:12]}"
        self.store.put(audit_id, {"item_id": item_id, "resolution": resolution, "audited_by": audited_by, "ts": value["audited_at"]})
        return self._from_dict(item_id, value)

    def audit_log(self) -> list[dict[str, Any]]:
        return [value for _, value in self.store.scan("queue:audit:")]

    def queue_depth(self) -> int:
        return sum(1 for _, v in self.store.scan("q:") if v["status"] == "pending")

    @staticmethod
    def _from_dict(item_id: str, value: dict[str, Any]) -> QueueItem:
        item = QueueItem(item_id, value["left"], value["right"], value["score"], value["ts"])
        item.status = value.get("status", "pending")
        item.resolution = value.get("resolution")
        item.audited_by = value.get("audited_by")
        item.audited_at = value.get("audited_at")
        return item
