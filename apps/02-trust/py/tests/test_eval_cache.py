"""A2 — deterministic per-sample eval cache (Airbnb Layer 2).

Properties under test:
1. Determinism: identical (sample, config) / (sample, output, judge, metric)
   inputs return identical cached bytes — no judge re-run, no majority-vote.
2. Resumability: a run failing at sample N resumes from the cache (only the
   missing samples recompute).
3. Write-through, no-overwrite semantics; key collisions with different
   content are an error (would hide a config bug).
4. File-backed persistence round-trip (JSONL, atomic persist).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from trust.confbench.eval_cache import CachedEval, EvalCache, cache_key, canonical_json


class TestCanonicalKeys:
    def test_key_order_insensitive(self):
        assert canonical_json({"b": 1, "a": [2, {"d": 3, "c": 4}]}) == canonical_json(
            {"a": [2, {"c": 4, "d": 3}], "b": 1}
        )

    def test_cache_key_is_deterministic(self):
        assert cache_key("ref", "s1", {"config": 1}) == cache_key("ref", "s1", {"config": 1})
        assert cache_key("ref", "s1", {"config": 1}) != cache_key("ref", "s1", {"config": 2})

    def test_axes_do_not_collide(self):
        assert cache_key("ref", "s1", {}) != cache_key("judge", "s1", "out", {}, "brier")


class TestEvalCache:
    def test_hit_miss_tracking(self):
        cache = EvalCache()
        key = cache_key("x", 1)
        assert cache.get(key) is None
        assert cache.misses == 1
        cache.put(key, {"score": 0.9})
        assert cache.get(key) == {"score": 0.9}
        assert cache.hits == 1
        assert cache.size == 1

    def test_write_through_never_overwrites_identical(self):
        cache = EvalCache()
        key = cache_key("x", 1)
        cache.put(key, {"score": 0.9})
        cache.put(key, {"score": 0.9})  # identical → no-op
        assert cache.size == 1

    def test_key_collision_with_different_content_errors(self):
        cache = EvalCache()
        cache.put("k", {"score": 0.9})
        with pytest.raises(ValueError, match="collision"):
            cache.put("k", {"score": 0.1})

    def test_file_backed_round_trip(self, tmp_path: Path):
        path = tmp_path / "cache.jsonl"
        cache = EvalCache(path)
        cache.put(cache_key("judge", "s1", "out1", {"judge": "v1"}, "brier"), 0.42)
        cache.put(cache_key("ref", "s1", {"cfg": "v1"}), ["chunk-a", "chunk-b"])
        reloaded = EvalCache(path)
        assert reloaded.size == 2
        assert reloaded.get(cache_key("judge", "s1", "out1", {"judge": "v1"}, "brier")) == 0.42

    def test_atomic_persist(self, tmp_path: Path):
        cache = EvalCache()
        cache.put("k1", 1)
        cache.put("k2", 2)
        path = tmp_path / "sub" / "cache.jsonl"
        cache.persist(path)
        assert EvalCache(path).size == 2


class TestCachedEval:
    def test_compute_runs_only_on_miss(self):
        cache = EvalCache()
        evals = CachedEval(cache)
        calls = {"n": 0}

        def compute():
            calls["n"] += 1
            return {"score": 0.5}

        a = evals.judge_score("s1", "out-1", {"judge": "v1"}, "brier", compute)
        b = evals.judge_score("s1", "out-1", {"judge": "v1"}, "brier", compute)
        assert a == b == {"score": 0.5}
        assert calls["n"] == 1  # second call served from cache

    def test_determinism_property_same_outputs(self):
        evals = CachedEval()
        assert evals.same_outputs({"a": 1, "b": [1, 2]}, {"b": [1, 2], "a": 1})

    def test_different_output_or_config_misses(self):
        cache = EvalCache()
        evals = CachedEval(cache)
        calls = {"n": 0}

        def compute(v):
            def inner():
                calls["n"] += 1
                return v

            return inner

        evals.judge_score("s1", "out-1", {"judge": "v1"}, "brier", compute(1))
        evals.judge_score("s1", "out-1", {"judge": "v1"}, "brier", compute(1))  # hit
        evals.judge_score("s1", "out-2", {"judge": "v1"}, "brier", compute(2))  # miss (output)
        evals.judge_score("s1", "out-1", {"judge": "v2"}, "brier", compute(3))  # miss (config)
        assert calls["n"] == 3


class TestResumability:
    def test_partial_cache_resumes(self, tmp_path: Path):
        """A run that dies at sample 4 recomputes only 4..9, not 0..9."""
        path = tmp_path / "cache.jsonl"
        cache = EvalCache(path)
        evals = CachedEval(cache)
        computed: list[int] = []

        # First run: computes 0..3, then 'crashes'
        for i in range(10):
            if i == 4:
                break  # simulate failure mid-run
            evals.reference(f"sample-{i}", {"cfg": 1}, lambda i=i: computed.append(i) or i)

        # Second run: same loop, full length
        for i in range(10):
            evals.reference(f"sample-{i}", {"cfg": 1}, lambda i=i: computed.append(i) or i)

        assert computed == [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
        assert evals.cache.stats()["hits"] == 4  # samples 0..3 served from cache

    def test_new_candidate_reuses_cached_references(self):
        """Adding a new candidate reuses cached model outputs (article: each
        new candidate runs against existing cached outputs for free)."""
        cache = EvalCache()
        evals = CachedEval(cache)
        refs = {i: f"output-{i}" for i in range(5)}
        ref_config = {"ref_generator": "v1"}  # reference generation config (stable)
        for i, out in refs.items():
            evals.reference(f"s{i}", ref_config, lambda out=out: out)

        # Candidate B scores the SAME cached references — no regeneration.
        for i, out in refs.items():
            got = evals.reference(f"s{i}", ref_config, lambda: "SHOULD-NOT-RUN")
            assert got == out

        # Candidates sharing a base model emit identical outputs on the
        # uncontested samples; the judge-score cache key includes the OUTPUT,
        # so identical outputs hit the cache across candidates (the article's
        # ">half of model outputs are identical strings" observation).
        shared_output = {"text": "same response both candidates"}
        for i in range(5):
            evals.judge_score(f"s{i}", shared_output, {"judge": "v1"}, "brier", lambda: 0.8)
        for i in range(5):
            got = evals.judge_score(f"s{i}", shared_output, {"judge": "v1"}, "brier", lambda: "SHOULD-NOT-RUN")
            assert got == 0.8

        # A divergent output (contested sample) is its own key.
        evals.judge_score("s0", {"text": "candidate-B-only"}, {"judge": "v1"}, "brier", lambda: 0.4)
        assert cache.get(cache_key("judge", "s0", {"text": "candidate-B-only"}, {"judge": "v1"}, "brier")) == 0.4
