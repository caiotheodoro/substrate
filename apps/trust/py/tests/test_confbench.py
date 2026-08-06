"""M1 ConfBench: tasks (A-T-07), holdout (A-T-10), shift generator (A-T-11),
banned baselines (A-T-12), metrics + runner (A-T-08/09)."""
import pytest

from trust.confbench.baselines import VerbalizedBaseline, all_baselines, self_report_channels_never_evidence
from trust.confbench.holdout import HoldoutSet, holdout_split
from trust.confbench.metrics import evaluate_scorer, ndcg_escalation
from trust.confbench.runner import run_confbench
from trust.confbench.shift_generator import ShiftSpec, apply_shift, difficulty_skew, self_report_inflation
from trust.confbench.tasks import ConfBenchTask, generate_tasks, load_confbench_tasks


class TestTaskGeneration:
    def test_deterministic_under_seed(self):
        a = generate_tasks(50, seed=3)
        b = generate_tasks(50, seed=3)
        assert [t.outcome for t in a] == [t.outcome for t in b]
        assert [t.evidence.to_row() for t in a] == [t.evidence.to_row() for t in b]

    def test_all_four_kinds_present(self):
        kinds = {t.kind for t in generate_tasks(100, seed=3)}
        assert kinds == {"tool", "retrieval", "schema", "outcome"}

    def test_shift_changes_distribution(self):
        base = generate_tasks(400, seed=4)
        shifted = generate_tasks(400, seed=4, shift=True)
        base_rate = sum(t.outcome for t in base) / len(base)
        shifted_rate = sum(t.outcome for t in shifted) / len(shifted)
        assert shifted_rate < base_rate  # harder workload fails more

    def test_evidence_never_contains_self_report(self):
        for t in generate_tasks(50, seed=4):
            assert self_report_channels_never_evidence(t)


class TestShiftGenerator:
    def test_difficulty_skew_raises_difficulty(self):
        tasks = generate_tasks(20, seed=1)
        shifted = difficulty_skew(tasks, 0.3, seed=2)
        assert all(s.difficulty >= t.difficulty for s, t in zip(shifted, tasks))

    def test_self_report_inflation_is_banned_channel_only(self):
        tasks = generate_tasks(20, seed=1)
        shifted = self_report_inflation(tasks, 0.5, seed=2)
        assert sum(s.self_report["verbalized"] for s in shifted) > sum(t.self_report["verbalized"] for t in tasks)
        assert all(s.evidence.features == t.evidence.features for s, t in zip(shifted, tasks))

    def test_apply_shift_composes(self):
        tasks = generate_tasks(20, seed=1)
        shifted = apply_shift(tasks, ShiftSpec(difficulty_shift=0.2, self_report_inflation=0.4), seed=3)
        assert len(shifted) == len(tasks)
        assert all(t.task_id == s.task_id for t, s in zip(tasks, shifted))


class TestHoldout:
    def test_disjoint_membership(self):
        tasks = generate_tasks(100, seed=2)
        train, holdout = holdout_split(tasks, holdout_ratio=0.3, seed=9)
        train_ids = {t.task_id for t in train}
        assert not (train_ids & holdout.task_ids)
        assert len(train_ids) == 70
        assert holdout.is_holdout(next(iter(holdout.task_ids)))

    def test_trap_documents_present(self):
        assert len(HoldoutSet().trap_documents) >= 3


class TestBaselines:
    def test_all_banned(self):
        for bl in all_baselines():
            assert bl.banned is True

    def test_channels_are_self_report_keys(self):
        for bl in all_baselines():
            assert bl.channel in ("logprob_norm", "self_consistency", "verbalized")

    def test_scores_read_task_channel(self):
        tasks = generate_tasks(10, seed=1)
        v = VerbalizedBaseline()
        assert [s for s in v.scores(tasks)] == [t.self_report["verbalized"] for t in tasks]


class TestMetrics:
    def test_ndcg_escalation_ascending_rewards_calibrated_channel(self):
        # calibrated channel: low confidence = failures -> review order good
        conf = [0.1, 0.2, 0.8, 0.9]
        worth = [1, 1, 0, 0]
        calibrated = ndcg_escalation(conf, worth)
        # confidently-wrong channel: failures carry HIGH confidence
        conf_bad = [0.9, 0.8, 0.2, 0.1]
        wrong = ndcg_escalation(conf_bad, worth)
        assert calibrated == pytest.approx(1.0)
        assert calibrated > wrong

    def test_evaluate_scorer_fields(self):
        ev = evaluate_scorer("x", [0.5, 0.5, 0.9], [1, 0, 1])
        assert ev.brier >= 0.0
        assert ev.ece >= 0.0
        assert ev.banned is False
        assert "ndcg_escalation" in ev.as_dict()


class TestRunner:
    def _fake_factory(self, train, base):
        import numpy as np

        def scores(tasks):
            out = []
            for t in tasks:
                row = t.evidence.to_row()
                logit = 1.2 * (row["retrieval_prob"] - 0.5) + 1.5 * row["schema_satisfied"] - 1.0 * row["tool_error"]
                out.append(1.0 / (1.0 + np.exp(-logit)))
            return out

        return scores

    def test_runner_end_to_end_with_fake_scorer(self, tmp_path):
        tasks = {
            "train": generate_tasks(60, seed=10),
            "base_eval": generate_tasks(40, seed=11),
            "shifted_eval": generate_tasks(40, seed=12, shift=True),
        }
        holdout = HoldoutSet(task_ids={t.task_id for t in tasks["base_eval"]})
        result = run_confbench(tasks, self._fake_factory, holdout=holdout, calibrate_baselines=True)
        assert "base" in result.evidence and "shifted" in result.evidence
        for suffix in ("logprob_norm", "self_consistency", "verbalized"):
            assert f"{suffix}-shifted" in result.baselines
            assert result.baselines[suffix].banned is True
        assert set(result.shift) >= {"brier_delta", "ece_delta", "ndcg_delta"}
        written = result.write(tmp_path)
        assert "confbench_report.json" in written
        assert (tmp_path / "confbench_report.json").exists()

    def test_runner_rejects_holdout_leak(self):
        tasks = {
            "train": generate_tasks(30, seed=10),
            "base_eval": generate_tasks(20, seed=11),
            "shifted_eval": generate_tasks(20, seed=12),
        }
        holdout = HoldoutSet(task_ids={tasks["train"][0].task_id})
        with pytest.raises(ValueError, match="holdout discipline"):
            run_confbench(tasks, self._fake_factory, holdout=holdout)

    def test_canonical_split_seeds(self):
        tasks = load_confbench_tasks()
        assert set(tasks) == {"train", "base_eval", "shifted_eval"}
        assert len(tasks["train"]) == 800
        assert len(tasks["base_eval"]) == 400
        assert len(tasks["shifted_eval"]) == 400


class TestRunnerCacheAdoption:
    """A2 — ConfBench runner with the deterministic eval cache: identical
    reruns are served from cache (same report bytes) and the second run
    recomputes nothing on the baseline axis."""

    def _fake_factory(self, train, base):
        import numpy as np

        def scores(tasks):
            out = []
            for t in tasks:
                row = t.evidence.to_row()
                logit = 1.2 * (row["retrieval_prob"] - 0.5) + 1.5 * row["schema_satisfied"] - 1.0 * row["tool_error"]
                out.append(1.0 / (1.0 + np.exp(-logit)))
            return out

        return scores

    def _small_tasks(self):
        from trust.confbench.tasks import generate_tasks

        return {
            "train": generate_tasks(60, seed=10),
            "base_eval": generate_tasks(40, seed=11),
            "shifted_eval": generate_tasks(40, seed=12),
        }

    def test_second_run_serves_baselines_from_cache_and_is_identical(self, tmp_path):
        from trust.confbench.eval_cache import EvalCache
        from trust.confbench.runner import run_confbench

        cache_path = tmp_path / "confbench-cache.jsonl"
        tasks = self._small_tasks()
        cache = EvalCache(cache_path)

        first = run_confbench(tasks, self._fake_factory, cache=cache)
        stats_after_first = dict(cache.stats())
        assert cache.size > 0

        reloaded = EvalCache(cache_path)
        second = run_confbench(tasks, self._fake_factory, cache=reloaded)
        assert reloaded.hits >= stats_after_first["entries"], "every cached baseline score should hit on rerun"
        assert reloaded.size == stats_after_first["entries"]
        assert second.metadata["cache"]["hits"] >= stats_after_first["entries"]
        a, b = first.as_dict(), second.as_dict()
        a.pop("metadata")
        b.pop("metadata")
        assert a == b  # eval content byte-identical; only cache stats differ

    def test_cache_metadata_recorded_in_report(self, tmp_path):
        from trust.confbench.eval_cache import EvalCache
        from trust.confbench.runner import run_confbench

        cache = EvalCache(tmp_path / "c.jsonl")
        result = run_confbench(self._small_tasks(), self._fake_factory, cache=cache)
        assert result.metadata["cache"]["entries"] > 0

    def test_interrupted_run_resumes(self, tmp_path):
        """A run that dies partway through baselines resumes: only the
        remaining samples compute (article: partial progress is durable)."""
        from trust.confbench.eval_cache import EvalCache, cache_baseline_scores

        cache = EvalCache(tmp_path / "c.jsonl")
        task_ids = [f"t{i}" for i in range(6)]
        compute = lambda: [float(i) for i in range(6)]

        # first attempt: 'dies' after scoring the first 3 samples
        cache_baseline_scores(cache, "bl", task_ids[:3], compute)
        assert cache.stats()["entries"] == 3
        # full rerun: only samples 3..5 recompute
        scores = cache_baseline_scores(cache, "bl", task_ids, compute)
        assert scores == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
        assert cache.stats()["hits"] == 3  # the first 3 served from cache
        assert cache.stats()["entries"] == 6
        assert cache.stats()["misses"] == 6  # 3 first run + 3 tail, nothing recomputed twice
