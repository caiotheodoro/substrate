"""P3 — human calibration as the difficulty oracle.

ARC-AGI's bar: every task attempted by 10 humans, fully solved by >=2
independently on first sight; difficulty is MEASURED, never estimated by a
judge. v1 uses a simulated oracle with calibrated noise (deterministic per
task id, so CI is reproducible); real humans via the knowledge :8202 /
harness HITL queues are the documented v2.

The oracle records, per task: how many of N attempts solved it, the solve
time, and per-solver action counts (the raw material for the RHAE human
baseline in Phase 3).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Protocol

from trust.forge.task import ForgeTask


@dataclass
class CalibrationOutcome:
    task_id: str
    n_attempts: int
    n_solved: int
    solve_time_s: float
    action_counts: list[int] = field(default_factory=list)

    @property
    def solved(self) -> bool:
        """ARC bar: at least 2 of the attempts solved it."""
        return self.n_solved >= 2

    def as_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "n_attempts": self.n_attempts,
            "n_solved": self.n_solved,
            "solve_time_s": round(self.solve_time_s, 2),
            "solved": self.solved,
            "action_counts": self.action_counts,
        }


class HumanOracle(Protocol):
    def calibrate(self, task: ForgeTask, n_attempts: int = 10) -> CalibrationOutcome: ...


def _seeded_float(key: str) -> float:
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


class SimulatedOracle:
    """Deterministic human oracle: P(solve | d) = sigmoid(k(d - d0)) with
    per-task noise seeded by the task id. ``k`` and ``d0`` define the
    population's skill; higher difficulty → lower solve probability."""

    def __init__(self, k: float = 6.0, d0: float = 0.5, action_base: int = 8) -> None:
        self.k = k
        self.d0 = d0
        self.action_base = action_base

    def _solve_probability(self, task: ForgeTask) -> float:
        d = task.difficulty_seed
        logit = self.k * (self.d0 - d)
        p = 1.0 / (1.0 + __import__("math").exp(-logit))
        # per-task irreducible noise (aleatoric ambiguity)
        noise = 0.05 * (_seeded_float(f"noise:{task.task_id}") - 0.5)
        return max(0.01, min(0.99, p + noise))

    def calibrate(self, task: ForgeTask, n_attempts: int = 10) -> CalibrationOutcome:
        p = self._solve_probability(task)
        n_solved = 0
        action_counts: list[int] = []
        for i in range(n_attempts):
            draw = _seeded_float(f"{task.task_id}:attempt:{i}")
            if draw < p:
                n_solved += 1
                # efficiency: harder tasks take more actions; scale by noise
                actions = self.action_base + int(round(task.difficulty_seed * 12 * (0.5 + _seeded_float(f"{task.task_id}:eff:{i}"))))
                action_counts.append(actions)
        solve_time_s = 60 + task.difficulty_seed * 540  # ARC-AGI-2: 30s..300s; 3: median 7.4min
        return CalibrationOutcome(
            task_id=task.task_id,
            n_attempts=n_attempts,
            n_solved=n_solved,
            solve_time_s=solve_time_s,
            action_counts=action_counts,
        )
