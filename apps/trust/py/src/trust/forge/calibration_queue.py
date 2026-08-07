"""P3-real — the real-human calibration queue (HANDOFF open path #1).

Wires ARC's 2-of-10 bar to actual human attempts instead of
``SimulatedOracle``. No live human pool is available yet (see
``docs/HANDOFF.md`` "honest limits") — this module is infra-ready and
protocol-conformant (``RealHumanOracle`` satisfies the same ``HumanOracle``
Protocol as ``SimulatedOracle``, so ``run_benchmark(oracle=...)`` needs
zero changes to consume it), proven by a mock-backed integration test. It
does NOT fabricate outcomes: ``calibrate()`` raises until a task's full
attempt quota has been submitted.

Storage is in-memory here to keep this module dependency-free; the natural
next step is backing it with a real store (see the ``Store`` protocol in
``apps/knowledge/py/.../core/storage.py``, already used by that unit's own
human-confirmation queue) or surfacing attempts through the harness HITL
dock (``apps/harness/src/hitl/hitl-dock.ts``, :8938) — neither existing
queue's schema fits a task/attempt/outcome record directly, so this is a
new, narrow queue rather than a reuse of either.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from trust.forge.calibration import CalibrationOutcome, HumanOracle
from trust.forge.task import ForgeTask


@dataclass
class AttemptResult:
    """One human's attempt at one task — the raw material a real
    calibration session submits, one per person per task."""

    task_id: str
    solved: bool
    action_count: int
    duration_s: float
    attempted_by: str


@dataclass
class CalibrationQueue:
    """Enqueue a task needing N human attempts; submit attempts as they
    come in; materialize a ``CalibrationOutcome`` once N are collected."""

    n_attempts_required: int = 10
    _attempts: dict[str, list[AttemptResult]] = field(default_factory=dict)

    def enqueue(self, task: ForgeTask) -> None:
        self._attempts.setdefault(task.task_id, [])

    def submit_attempt(self, result: AttemptResult) -> None:
        self._attempts.setdefault(result.task_id, []).append(result)

    def pending(self) -> dict[str, int]:
        """task_id -> attempts still needed, for every task not yet ready."""
        return {
            tid: self.n_attempts_required - len(atts)
            for tid, atts in self._attempts.items()
            if len(atts) < self.n_attempts_required
        }

    def is_ready(self, task_id: str) -> bool:
        return len(self._attempts.get(task_id, [])) >= self.n_attempts_required

    def outcome(self, task_id: str) -> CalibrationOutcome:
        atts = self._attempts.get(task_id, [])
        if len(atts) < self.n_attempts_required:
            raise ValueError(
                f"task {task_id} has only {len(atts)}/{self.n_attempts_required} attempts — "
                "cannot materialize an outcome yet"
            )
        solved = [a for a in atts if a.solved]
        return CalibrationOutcome(
            task_id=task_id,
            n_attempts=len(atts),
            n_solved=len(solved),
            solve_time_s=(sum(a.duration_s for a in atts) / len(atts)) if atts else 0.0,
            action_counts=[a.action_count for a in solved],
        )


@dataclass
class RealHumanOracle:
    """Satisfies ``HumanOracle`` (``calibrate(task, n_attempts=10) ->
    CalibrationOutcome``) by reading from a ``CalibrationQueue`` instead of
    simulating. Never fabricates: raises ``RuntimeError`` if the task's
    attempt quota isn't fully collected. Callers own the human-review loop
    that calls ``queue.submit_attempt`` as real results arrive."""

    queue: CalibrationQueue

    def calibrate(self, task: ForgeTask, n_attempts: int = 10) -> CalibrationOutcome:
        if not self.queue.is_ready(task.task_id):
            pending = self.queue.pending().get(task.task_id, n_attempts)
            raise RuntimeError(
                f"task {task.task_id} not yet calibrated: {pending} human attempt(s) still "
                "needed. RealHumanOracle does not fabricate outcomes — submit_attempt() for "
                "every required attempt before calling calibrate()."
            )
        return self.queue.outcome(task.task_id)
