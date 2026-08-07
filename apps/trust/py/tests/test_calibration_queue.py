"""Real-human calibration queue (HANDOFF open path #1).

Gate: RealHumanOracle satisfies the same HumanOracle protocol as
SimulatedOracle (calibrate(task) -> CalibrationOutcome), is injectable into
run_benchmark(oracle=...) with zero changes elsewhere, and NEVER fabricates
an outcome for a task that hasn't collected its full attempt quota —
it raises instead. No live human pool is wired up (there is none available
yet); this only proves protocol conformance against a mock attempt feed.
"""
from __future__ import annotations

import pytest

from trust.forge.calibration import CalibrationOutcome, HumanOracle
from trust.forge.calibration_queue import AttemptResult, CalibrationQueue, RealHumanOracle
from trust.forge.generators import ToolUseTaskGenerator


class TestCalibrationQueue:
    def test_enqueue_then_submit_reaches_ready(self):
        q = CalibrationQueue(n_attempts_required=3)
        task = ToolUseTaskGenerator().generate(n=1)[0]
        q.enqueue(task)
        assert not q.is_ready(task.task_id)
        assert q.pending()[task.task_id] == 3

        q.submit_attempt(AttemptResult(task.task_id, solved=True, action_count=4, duration_s=12.0, attempted_by="h1"))
        q.submit_attempt(AttemptResult(task.task_id, solved=False, action_count=8, duration_s=30.0, attempted_by="h2"))
        assert not q.is_ready(task.task_id)

        q.submit_attempt(AttemptResult(task.task_id, solved=True, action_count=5, duration_s=15.0, attempted_by="h3"))
        assert q.is_ready(task.task_id)
        assert task.task_id not in q.pending()

    def test_outcome_reflects_submitted_attempts(self):
        q = CalibrationQueue(n_attempts_required=2)
        task = ToolUseTaskGenerator().generate(n=1)[0]
        q.enqueue(task)
        q.submit_attempt(AttemptResult(task.task_id, solved=True, action_count=6, duration_s=10.0, attempted_by="h1"))
        q.submit_attempt(AttemptResult(task.task_id, solved=True, action_count=4, duration_s=8.0, attempted_by="h2"))

        outcome = q.outcome(task.task_id)
        assert isinstance(outcome, CalibrationOutcome)
        assert outcome.n_attempts == 2
        assert outcome.n_solved == 2
        assert outcome.solved  # ARC 2-of-10 bar
        assert sorted(outcome.action_counts) == [4, 6]

    def test_outcome_raises_before_quota_reached(self):
        q = CalibrationQueue(n_attempts_required=5)
        task = ToolUseTaskGenerator().generate(n=1)[0]
        q.enqueue(task)
        q.submit_attempt(AttemptResult(task.task_id, solved=True, action_count=4, duration_s=10.0, attempted_by="h1"))
        with pytest.raises(ValueError):
            q.outcome(task.task_id)


class TestRealHumanOracle:
    def test_satisfies_human_oracle_protocol(self):
        oracle = RealHumanOracle(queue=CalibrationQueue(n_attempts_required=2))
        assert isinstance(oracle, HumanOracle)

    def test_calibrate_raises_when_not_ready_never_fabricates(self):
        q = CalibrationQueue(n_attempts_required=2)
        task = ToolUseTaskGenerator().generate(n=1)[0]
        q.enqueue(task)
        oracle = RealHumanOracle(queue=q)
        with pytest.raises(RuntimeError):
            oracle.calibrate(task)

    def test_calibrate_returns_outcome_once_quota_met(self):
        q = CalibrationQueue(n_attempts_required=2)
        task = ToolUseTaskGenerator().generate(n=1)[0]
        q.enqueue(task)
        q.submit_attempt(AttemptResult(task.task_id, solved=True, action_count=5, duration_s=9.0, attempted_by="h1"))
        q.submit_attempt(AttemptResult(task.task_id, solved=False, action_count=9, duration_s=20.0, attempted_by="h2"))
        oracle = RealHumanOracle(queue=q)
        # explicit n_attempts=2, matching what's actually been submitted —
        # calibrate() honors its own argument now rather than silently
        # checking against the queue's n_attempts_required regardless of
        # what was asked for (see test_calibrate_honors_its_own_n_attempts_argument)
        outcome = oracle.calibrate(task, n_attempts=2)
        assert outcome.task_id == task.task_id
        assert outcome.n_attempts == 2

    def test_calibrate_honors_its_own_n_attempts_argument(self):
        """HumanOracle.calibrate(task, n_attempts=10) is part of the
        Protocol's actual signature — SimulatedOracle runs exactly the
        requested count. A prior version of RealHumanOracle silently
        ignored the parameter entirely and always checked readiness
        against the queue's own fixed n_attempts_required, so it satisfied
        the Protocol's signature but not its contract: it wasn't really
        substitutable for SimulatedOracle under a non-default quota."""
        q = CalibrationQueue(n_attempts_required=10)  # queue's own default
        task = ToolUseTaskGenerator().generate(n=1)[0]
        q.enqueue(task)
        for i in range(3):
            q.submit_attempt(
                AttemptResult(task.task_id, solved=(i < 2), action_count=4 + i, duration_s=9.0, attempted_by=f"h{i}")
            )
        oracle = RealHumanOracle(queue=q)
        # asking for exactly 3 (what's actually been submitted) must
        # succeed even though the queue's own quota is 10 and isn't met
        outcome = oracle.calibrate(task, n_attempts=3)
        assert outcome.n_attempts == 3
        assert outcome.n_solved == 2
        # asking for more than what's been submitted must still raise,
        # not silently fall back to "whatever the queue's default says"
        with pytest.raises(RuntimeError):
            oracle.calibrate(task, n_attempts=5)
