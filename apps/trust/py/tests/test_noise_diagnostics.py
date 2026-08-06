"""A3 — noise diagnostics (Airbnb Layer 1: name the noise).

The diagnostic separates reference-regeneration noise from judge drift so
score movement can be attributed. Also demonstrates the Layer-2 fix: with
the eval cache holding references stable (``regenerate_reference=False``),
the regeneration rate is zero by construction.
"""
from __future__ import annotations

from trust.confbench.eval_cache import EvalCache, CachedEval
from trust.confbench.noise_diagnostics import (
    SeededNoisyJudge,
    SeededNoisyReferenceGenerator,
    measure_noise,
    sample_hash,
)

SAMPLES = [f"s{i}" for i in range(50)]


class TestSampleHash:
    def test_byte_stable(self):
        assert sample_hash({"b": 1, "a": 2}) == sample_hash({"a": 2, "b": 1})

    def test_different_content_different_hash(self):
        assert sample_hash("x") != sample_hash("y")


class TestNoiseDiagnostics:
    def test_reference_regeneration_rate_observed(self):
        gen = SeededNoisyReferenceGenerator(seed=7, noise_rate=0.75)
        judge = SeededNoisyJudge(seed=11, drift_rate=0.0)
        report = measure_noise(SAMPLES, gen, judge)
        assert 0.5 < report.reference_regeneration_rate <= 0.9, report.reference_regeneration_rate
        assert report.judge_drift_rate == 0.0

    def test_judge_drift_rate_observed(self):
        gen = SeededNoisyReferenceGenerator(seed=7, noise_rate=0.0)
        judge = SeededNoisyJudge(seed=11, drift_rate=0.1)
        report = measure_noise(SAMPLES, gen, judge)
        assert report.reference_regeneration_rate == 0.0
        assert 0.0 < report.judge_drift_rate <= 0.3, report.judge_drift_rate

    def test_judge_sensitive_split(self):
        gen = SeededNoisyReferenceGenerator(seed=7, noise_rate=0.0)
        judge = SeededNoisyJudge(seed=11, drift_rate=0.2, drift_magnitude=0.3)
        report = measure_noise(SAMPLES, gen, judge)
        assert len(report.judge_sensitive_samples) == report.as_dict()["n_judge_sensitive"]
        assert len(report.judge_stable_samples) == report.as_dict()["n_judge_stable"]
        assert len(report.judge_sensitive_samples) + len(report.judge_stable_samples) == report.n_samples

    def test_stable_reference_store_kills_regeneration(self):
        """The A2 fix: cache the references — regeneration rate drops to zero."""
        gen = SeededNoisyReferenceGenerator(seed=7, noise_rate=0.75)
        judge = SeededNoisyJudge(seed=11, drift_rate=0.0)
        report = measure_noise(SAMPLES, gen, judge, regenerate_reference=False)
        assert report.reference_regeneration_rate == 0.0

    def test_report_serializable_and_writable(self, tmp_path):
        gen = SeededNoisyReferenceGenerator(seed=7, noise_rate=0.75)
        judge = SeededNoisyJudge(seed=11, drift_rate=0.1)
        report = measure_noise(SAMPLES, gen, judge)
        out = tmp_path / "validation" / "judge-drift.json"
        report.write(out)
        assert out.exists()
        import json

        data = json.loads(out.read_text())
        assert set(data) == {
            "n_samples",
            "reference_regeneration_rate",
            "judge_drift_rate",
            "n_judge_sensitive",
            "n_judge_stable",
            "diagnostics",
        }


class TestDiagnosticIntegration:
    def test_cached_reference_axis_matches_diagnostic(self):
        """The A2 cache and the A3 diagnostic agree: caching a reference makes
        it stable (no regeneration) — the fix for the measured noise."""
        cache = EvalCache()
        evals = CachedEval(cache)
        gen = SeededNoisyReferenceGenerator(seed=7, noise_rate=0.75)

        stored = {sid: evals.reference(sid, {"cfg": 1}, lambda sid=sid: gen(sid)) for sid in SAMPLES}

        # regenerate the same references through the cache — identical outputs
        regen = {sid: evals.reference(sid, {"cfg": 1}, lambda: "SHOULD-NOT-RUN") for sid in SAMPLES}
        assert stored == regen
        assert cache.hits == len(SAMPLES)
