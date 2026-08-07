"""S6 — judge-ladder budget study.

Gate: a perfect judge (agrees with ground truth on every task) should be
able to auto-resolve tasks at threshold 0.5 with NO loss in calibration
monotonicity vs threshold 0.0 (no screening) while cutting the attempt
budget; a random/noise judge should not — this is the tradeoff curve the
study exists to measure.
"""
from __future__ import annotations

from trust.forge.calibration import SimulatedOracle
from trust.forge.generators import ToolUseTaskGenerator
from trust.forge.studies.s6_judge_ladder import N_ATTEMPTS, run_sweep


class TestJudgeLadder:
    def test_perfect_judge_saves_budget_without_full_data_loss(self):
        tasks = ToolUseTaskGenerator().generate(n=40)
        oracle = SimulatedOracle()
        ground_truth = {t.task_id: oracle.calibrate(t) for t in tasks}

        def perfect_judge(task):
            o = ground_truth[task.task_id]
            rate = o.n_solved / max(o.n_attempts, 1)
            return 1.0 - rate  # judge score: high = hard, mirrors solve rate exactly

        results = run_sweep(tasks, oracle, perfect_judge, thresholds=[0.0, 0.5])
        no_screen = results["thresholds"]["0.0"]
        full_screen = results["thresholds"]["0.5"]

        assert no_screen["n_auto_resolved"] == 0
        assert no_screen["attempt_budget_fraction"] == 1.0
        assert full_screen["n_auto_resolved"] > 0
        assert full_screen["attempt_budget_fraction"] < 1.0

    def test_thresholds_report_full_budget_at_zero(self):
        tasks = ToolUseTaskGenerator().generate(n=20)
        oracle = SimulatedOracle()
        results = run_sweep(tasks, oracle, judge_fn=lambda t: 0.5, thresholds=[0.0])
        r = results["thresholds"]["0.0"]
        assert r["attempt_budget_used"] == N_ATTEMPTS * len(tasks)

    def test_confident_judge_auto_resolves_everything_at_wide_threshold(self):
        tasks = ToolUseTaskGenerator().generate(n=15)
        oracle = SimulatedOracle()
        # judge fires maximally confident (always says "trivial") — should
        # auto-resolve every task at a wide-enough threshold
        results = run_sweep(tasks, oracle, judge_fn=lambda t: 0.0, thresholds=[0.5])
        r = results["thresholds"]["0.5"]
        assert r["n_auto_resolved"] == len(tasks)
        assert r["attempt_budget_used"] == 0
