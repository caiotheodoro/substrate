"""The Forge orchestrator — generate → verify → gauntlet → survivors.

P1: every task carries a passing programmatic verifier.
P2: every task survives the gauntlet before any human/judge touches it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from trust.forge.gauntlet import GauntletResult, run_gauntlet
from trust.forge.task import ForgeTask


@dataclass
class ForgeOutput:
    tasks: list[ForgeTask] = field(default_factory=list)
    gauntlet: dict[str, GauntletResult] = field(default_factory=dict)

    @property
    def pass_rate(self) -> float:
        if not self.gauntlet:
            return 0.0
        return sum(1 for r in self.gauntlet.values() if r.passed) / len(self.gauntlet)

    def as_dict(self) -> dict[str, object]:
        return {
            "n_tasks": len(self.tasks),
            "pass_rate": round(self.pass_rate, 4),
            "survivors": [t.as_dict() for t in self.tasks if self.gauntlet.get(t.task_id, GauntletResult(t.task_id, False)).passed],
            "gauntlet": {tid: r.as_dict() for tid, r in self.gauntlet.items()},
        }


def forge_tasks(
    generator: Callable[[], list[ForgeTask]],
    *,
    min_pass_rate: float = 0.95,
    corpus: list[ForgeTask] | None = None,
) -> ForgeOutput:
    """Run the full forge pipeline. Fails loudly if fewer than
    ``min_pass_rate`` of generated tasks survive the gauntlet (the phase-1
    validation gate)."""
    tasks = generator()
    # Accumulate the corpus as tasks are gauntleted, in order: each task's
    # NoveltyCheck runs against everything processed so far (the caller's
    # prior corpus plus this batch's own earlier tasks), then the task
    # itself joins the corpus for whatever comes after it. Previously
    # `corpus` was fixed at whatever the caller passed in (empty by
    # default) for every task in the batch, so a generator that produces
    # duplicate signatures WITHIN one call was never caught — novelty was
    # checked against an empty list every time.
    running_corpus: list[ForgeTask] = list(corpus) if corpus else []
    gauntlet: dict[str, GauntletResult] = {}
    for t in tasks:
        gauntlet[t.task_id] = run_gauntlet(t, running_corpus)
        running_corpus.append(t)
    survivors = [t for t in tasks if gauntlet[t.task_id].passed]
    output = ForgeOutput(tasks=tasks, gauntlet=gauntlet)
    if output.pass_rate < min_pass_rate:
        failures = [tid for tid, r in gauntlet.items() if not r.passed]
        raise ValueError(
            f"forge gate: {output.pass_rate:.2%} pass rate < {min_pass_rate:.2%} "
            f"({len(failures)} failures: {failures[:5]})"
        )
    return output
