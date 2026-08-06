"""A-T-10 confbench-holdout — membership sets + trap documents, never leaked.

The ConfBench training split is membership-disjoint from the evaluation sets
by construction; the holdout object additionally fingerprints every task id
and carries the trap documents the shift-generator and contamination gate use
as leakage references.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from trust.confbench.tasks import ConfBenchTask

# Documents a *synthetic-data generator* would plausibly mislabel (R4 traps):
# the answer contradicts the document. The contamination gate checks seeds
# against these the same way it checks the evaluation set.
TRAP_DOCUMENTS: list[str] = [
    "The launch was reported as a complete failure in the telemetry log, contrary to the press release.",
    "Version 2.3 of the library removed the feature that version 2.2 documented as stable.",
    "The schema requires a numeric `amount`; the example payload carried a string.",
    "The experiment concluded the treatment had no measurable effect, though the abstract claims otherwise.",
]


@dataclass
class HoldoutSet:
    """Disjoint membership: ids in the holdout never appear in training data."""

    task_ids: set[str] = field(default_factory=set)
    trap_documents: list[str] = field(default_factory=lambda: list(TRAP_DOCUMENTS))

    def is_holdout(self, task_id: str) -> bool:
        return task_id in self.task_ids

    def as_dict(self) -> dict[str, Any]:
        return {"task_ids": sorted(self.task_ids), "trap_documents": self.trap_documents}


def holdout_split(tasks: list[ConfBenchTask], holdout_ratio: float = 0.2, seed: int = 7) -> tuple[list[ConfBenchTask], HoldoutSet]:
    """Split tasks into train + holdout with the holdout recorded in a
    ``HoldoutSet``. The holdout set is the evaluation set; its ids are
    recorded so nothing downstream can leak them into training data."""
    import random

    rng = random.Random(seed)
    ids = [t.task_id for t in tasks]
    rng.shuffle(ids)
    k = max(1, int(holdout_ratio * len(ids)))
    holdout_ids = set(ids[:k])
    train = [t for t in tasks if t.task_id not in holdout_ids]
    return train, HoldoutSet(task_ids=holdout_ids)
