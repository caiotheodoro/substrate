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
from typing import Protocol, runtime_checkable

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


@runtime_checkable
class HumanOracle(Protocol):
    def calibrate(self, task: ForgeTask, n_attempts: int = 10) -> CalibrationOutcome: ...


def _seeded_float(key: str) -> float:
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


class SimulatedOracle:
    """Deterministic human oracle: P(solve | d) = sigmoid(k(d - d0)) with
    per-task noise seeded by the task id. ``k`` and ``d0`` define the
    population's skill; higher difficulty → lower solve probability."""

    def __init__(self, k: float = 6.0, d0: float = 0.5, noise_scale: float = 0.05) -> None:
        self.k = k
        self.d0 = d0
        self.noise_scale = noise_scale

    def _solve_probability(self, task: ForgeTask) -> float:
        d = task.difficulty_seed
        logit = self.k * (self.d0 - d)
        p = 1.0 / (1.0 + __import__("math").exp(-logit))
        # per-task irreducible noise (aleatoric ambiguity), magnitude
        # configurable via noise_scale — a prior version hardcoded 0.05
        # unconditionally, which made S1's oracle-noise sweep construct
        # an identical oracle at every one of its 5 swept values.
        noise = self.noise_scale * (_seeded_float(f"noise:{task.task_id}") - 0.5)
        return max(0.01, min(0.99, p + noise))

    def calibrate(self, task: ForgeTask, n_attempts: int = 10) -> CalibrationOutcome:
        p = self._solve_probability(task)
        n_solved = 0
        action_counts: list[int] = []
        # Human action counts are grounded in the task's OWN minimal path
        # length (len(task.expected)), not a flat task-independent constant.
        # RHAE's efficiency ratio is human_baseline / agent_actions, and any
        # solver that actually solves a task (PerfectSolver, GreedySolver,
        # LlmSolver on a clean run) uses close to the task's own minimal
        # number of calls — a flat baseline unrelated to that length always
        # blows past the 1.15 cap for every task, collapsing RHAE to solve
        # rate with zero efficiency signal (see benchmark.py / rhae.py).
        # Overhead here models real human inefficiency: somewhere between
        # "found the exact minimal path" (1.0x) and "explored a fair bit
        # before landing on it" (~2.2x at max difficulty + noise), scaled by
        # the task's own difficulty so harder tasks show more overhead.
        n_calls = max(1, len(task.expected))
        for i in range(n_attempts):
            draw = _seeded_float(f"{task.task_id}:attempt:{i}")
            if draw < p:
                n_solved += 1
                overhead = 1.0 + task.difficulty_seed * 0.7 + 0.5 * _seeded_float(f"{task.task_id}:eff:{i}")
                actions = max(n_calls, int(round(n_calls * overhead)))
                action_counts.append(actions)
        solve_time_s = 60 + task.difficulty_seed * 540  # ARC-AGI-2: 30s..300s; 3: median 7.4min
        return CalibrationOutcome(
            task_id=task.task_id,
            n_attempts=n_attempts,
            n_solved=n_solved,
            solve_time_s=solve_time_s,
            action_counts=action_counts,
        )
