"""Per-run analysis artifact (analysis.py).

Gate: n_tasks must reflect the actual scored population whether analyze()
is called on a live BenchmarkRun (from run_benchmark) or reconstructed
from a saved artifact (the CLI path, main()) — a prior version only
worked for the former, since the CLI path rebuilds BenchmarkRun with
tasks=[] and analyze() read len(run.tasks) directly.
"""
from __future__ import annotations

from trust.forge.analysis import analyze
from trust.forge.benchmark import BenchmarkRun, run_benchmark


class TestAnalyzeNTasks:
    def test_n_tasks_correct_on_a_live_run(self):
        run = run_benchmark(n_tasks=30, seed=2, verbose=False)
        result = analyze(run)
        assert result["n_tasks"] == len(run.difficulty)
        assert result["n_tasks"] > 0

    def test_n_tasks_correct_when_reconstructed_without_task_objects(self):
        """Mirrors analysis.py's main(): the CLI rebuilds a BenchmarkRun
        from a saved JSON artifact, where the actual ForgeTask objects
        aren't available (only their ids and computed fields) — tasks=[]
        is passed deliberately. n_tasks must still reflect the real
        scored population size, not the empty placeholder list."""
        live = run_benchmark(n_tasks=25, seed=4, verbose=False)
        reconstructed = BenchmarkRun(
            name=live.name,
            seed=live.seed,
            tasks=[],  # exactly what main() does -- no task objects available
            calibration=live.calibration,
            difficulty=live.difficulty,
            splits=live.splits,
            scores=live.scores,
            contamination=live.contamination,
            metadata=live.metadata,
        )
        result = analyze(reconstructed)
        assert result["n_tasks"] == len(live.difficulty)
        assert result["n_tasks"] > 0
