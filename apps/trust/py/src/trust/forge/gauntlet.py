"""The gauntlet (P2) — pre-calibration validation, ported from ARC-AGI-3 §3.5.

Every generated task must survive, before any human or judge touches it:

1. **Random-policy floor** — a seeded random/naive agent must not "solve"
   the task more than 1 in 10,000 attempts (ARC-AGI-3 §3.5.2). On our
   deterministic registry the solver is a seeded random agent drawing from
   the task's tool space; the floor is measured over rollouts.
2. **Fuzz sweep** — malformed/adversarial inputs must not crash the tool
   registry and must not accidentally verify.
3. **Reproducibility** — the reference trajectory re-runs byte-identically
   (harness golden-replay discipline).
4. **Novelty** — tasks too similar to the existing corpus are flagged: two
   tasks share a tool-sequence prefix and arg-space (the compression-based
   distinctness test, ARC-AGI-3 §3.5).

Only survivors reach calibration.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from typing import Any, Callable

from trust.forge.task import ForgeTask, ToolCall


@dataclass
class GauntletResult:
    task_id: str
    passed: bool
    checks: dict[str, bool] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"task_id": self.task_id, "passed": self.passed, "checks": self.checks, "details": self.details}


class RandomPolicyFloor:
    """A seeded random agent draws tool calls from the task's tool space.
    If it produces a trajectory that verifies, the task is trivially
    solvable by chance — reject (ARC: max 1 in 10,000)."""

    def __init__(self, seed: int = 7, attempts: int = 2000) -> None:
        self.seed = seed
        self.attempts = attempts
        self.threshold = 1 / 10_000

    def check(self, task: ForgeTask) -> GauntletResult:
        rng = random.Random(f"{self.seed}:{task.task_id}")
        by_name = {t.name: t for t in task.tools}
        names = list(by_name)
        solutions = 0
        for _ in range(self.attempts):
            length = rng.randint(1, max(len(task.expected), 2))
            trajectory: list[dict[str, Any]] = []
            for _ in range(length):
                name = rng.choice(names)
                tool = by_name[name]
                args = _random_args(rng, tool.input_schema)
                try:
                    result = tool(args)
                except Exception:
                    result = {"ok": False, "error": "crash"}
                trajectory.append({"name": name, "args": args, "result": result})
            if task.verify(trajectory):
                solutions += 1
        rate = solutions / self.attempts
        return GauntletResult(
            task_id=task.task_id,
            passed=rate <= self.threshold,
            checks={"random_policy_floor": rate <= self.threshold},
            details={"solve_rate": rate, "solutions": solutions, "attempts": self.attempts},
        )


class FuzzSweep:
    """Malformed args (wrong types, unknown keys, empty) must not crash the
    registry and must not accidentally verify a clean task."""

    def __init__(self, seed: int = 11, sweeps: int = 200) -> None:
        self.seed = seed
        self.sweeps = sweeps

    def check(self, task: ForgeTask) -> GauntletResult:
        rng = random.Random(f"{self.seed}:{task.task_id}")
        crashes = 0
        false_verifies = 0
        by_name = {t.name: t for t in task.tools}
        for _ in range(self.sweeps):
            name = rng.choice(list(by_name))
            args: dict[str, Any] = rng.choice([{}, {"x": 1}, {"text": 7}, {"path": None}, {"set": 3}])
            try:
                result = by_name[name](args)
            except Exception:
                crashes += 1
                result = {"ok": False, "error": "crash"}
            trajectory = [{"name": name, "args": args, "result": result}]
            if task.verify(trajectory):
                false_verifies += 1
        passed = crashes == 0 and false_verifies == 0
        return GauntletResult(
            task_id=task.task_id,
            passed=passed,
            checks={"fuzz_no_crash": crashes == 0, "fuzz_no_false_verify": false_verifies == 0},
            details={"crashes": crashes, "false_verifies": false_verifies},
        )


class ReproducibilityCheck:
    """The reference trajectory re-runs byte-identically (golden replay)."""

    def check(self, task: ForgeTask) -> GauntletResult:
        by_name = {t.name: t for t in task.tools}
        run = [{"name": c.name, "args": c.args, "result": by_name[c.name](c.args)} for c in task.expected]
        run2 = [{"name": c.name, "args": c.args, "result": by_name[c.name](c.args)} for c in task.expected]
        identical = json.dumps(run, sort_keys=True) == json.dumps(run2, sort_keys=True)
        verifies = task.verify(run)
        return GauntletResult(
            task_id=task.task_id,
            passed=identical and verifies,
            checks={"reproducible": identical, "reference_verifies": verifies},
            details={},
        )


class NoveltyCheck:
    """Compression-based distinctness: a task is too similar to the corpus
    if it shares the full tool-sequence prefix and the same arg keys (the
    'one program solves both at <50% length' proxy, ARC-AGI-3 §3.5)."""

    def __init__(self, corpus: list[ForgeTask] | None = None) -> None:
        self.corpus: list[ForgeTask] = corpus or []

    def _signature(self, task: ForgeTask) -> tuple[tuple[str, ...], frozenset[str]]:
        seq = tuple(c.name for c in task.expected)
        keys = frozenset(k for c in task.expected for k in c.args)
        return seq, keys

    def check(self, task: ForgeTask) -> GauntletResult:
        sig = self._signature(task)
        similar = [t.task_id for t in self.corpus if self._signature(t) == sig]
        return GauntletResult(
            task_id=task.task_id,
            passed=len(similar) == 0,
            checks={"novel": len(similar) == 0},
            details={"similar_to": similar},
        )


def _random_args(rng: random.Random, schema: dict[str, Any]) -> dict[str, Any]:
    args: dict[str, Any] = {}
    props = schema.get("properties", {})
    for key, spec in props.items():
        if spec.get("type") == "string":
            args[key] = f"x{rng.randint(0, 99)}"
        elif spec.get("type") == "integer":
            args[key] = rng.randint(0, 9)
    return args


def run_gauntlet(task: ForgeTask, corpus: list[ForgeTask] | None = None) -> GauntletResult:
    """Full gauntlet: random floor → fuzz → reproducibility → novelty."""
    checks = [
        RandomPolicyFloor().check(task),
        FuzzSweep().check(task),
        ReproducibilityCheck().check(task),
        NoveltyCheck(corpus).check(task),
    ]
    return GauntletResult(
        task_id=task.task_id,
        passed=all(c.passed for c in checks),
        checks={k: v for c in checks for k, v in c.checks.items()},
        details={k: v for c in checks for k, v in c.details.items()},
    )
