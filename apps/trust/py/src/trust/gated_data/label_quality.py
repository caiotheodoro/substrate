"""A-T-24 label-quality-gate (v1-lite) — sampling + HITL review queue.

A deterministic sample of seeds goes to a review queue; a reviewer (human in
production, deterministic fake in tests) marks each item pass/fail. v1-lite
means: the queue is in-memory, and only the sampled fraction is reviewed.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Protocol

from trust.gated_data.models import GateVerdictResult, SeedRecord


@dataclass
class ReviewItem:
    sample_id: str
    content: str
    label: bool
    source: str
    decision: bool | None = None
    reviewer: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "sample_id": self.sample_id,
            "content": self.content,
            "label": self.label,
            "source": self.source,
            "decision": self.decision,
            "reviewer": self.reviewer,
        }


class Reviewer(Protocol):
    def review(self, item: ReviewItem) -> bool: ...


class AutoReviewer:
    """Deterministic fake reviewer: passes items whose label matches their
    metadata signal (the HITL stand-in for offline runs)."""

    def review(self, item: ReviewItem) -> bool:
        return item.label


class ReviewQueue:
    """In-memory review queue (A-T-24 lite)."""

    def __init__(self) -> None:
        self._items: dict[str, ReviewItem] = {}

    def enqueue(self, item: ReviewItem) -> None:
        self._items[item.sample_id] = item

    def pending(self) -> list[ReviewItem]:
        return [i for i in self._items.values() if i.decision is None]

    def resolve(self, sample_id: str, decision: bool, reviewer: str = "human") -> None:
        self._items[sample_id].decision = decision
        self._items[sample_id].reviewer = reviewer

    def decision_for(self, sample_id: str) -> bool | None:
        item = self._items.get(sample_id)
        return item.decision if item else None


class LabelQualityGate:
    """Samples a fraction of seeds into the review queue and applies the
    reviewer's decision; unsampled seeds pass (v1-lite)."""

    def __init__(self, sample_rate: float = 0.5, reviewer: Reviewer | None = None, queue: ReviewQueue | None = None, seed: int = 42) -> None:
        self.sample_rate = sample_rate
        self.reviewer = reviewer or AutoReviewer()
        self.queue = queue or ReviewQueue()
        self._seed = seed

    def evaluate(self, seed: SeedRecord) -> GateVerdictResult:
        rng = random.Random(f"{self._seed}:{seed.sample_id}")
        if rng.random() > self.sample_rate:
            return GateVerdictResult("label_quality", True, "unsampled", {"sampled": False})
        item = ReviewItem(seed.sample_id, seed.content, seed.label, seed.source)
        self.queue.enqueue(item)
        decision = self.reviewer.review(item)
        self.queue.resolve(item.sample_id, decision, reviewer=type(self.reviewer).__name__)
        return GateVerdictResult(
            "label_quality",
            decision,
            "accepted" if decision else "rejected by review",
            {"sampled": True, "reviewer": type(self.reviewer).__name__},
        )
