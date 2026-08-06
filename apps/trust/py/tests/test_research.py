"""M6 research: r1-dominance on a tiny synthetic shift (A-T-34 — acceptance 1)
and r2-verifiability audit (A-T-35)."""
from trust.confbench.tasks import generate_tasks
from trust.research.r1_dominance import run_r1
from trust.research.r2_verifiability import audit_seeds, audit_tasks, run_r2


def _tiny_tasks():
    return {
        "train": generate_tasks(300, seed=77),
        "base_eval": generate_tasks(200, seed=78),
        "shifted_eval": generate_tasks(200, seed=79, shift=True),
    }


class TestR1Dominance:
    def test_tiny_synthetic_shift(self, tmp_path):
        result = run_r1(_tiny_tasks(), out_dir=tmp_path)
        assert result["dominance"]["evidence_beats_best_baseline_brier_shifted"] is True
        assert result["dominance"]["evidence_beats_best_baseline_ece_shifted"] is True
        assert result["dominance"]["evidence_beats_best_baseline_ndcg_shifted"] is True
        assert result["ece_shifted"]["evidence"] < result["ece_shifted"]["verbalized"]
        assert result["brier_shifted"]["evidence"] < result["brier_shifted"]["logprob_norm"]
        assert (tmp_path / "r1_dominance.json").exists()
        assert (tmp_path / "r1_reliability.png").exists()

    def test_base_calibration_is_roughly_equal(self):
        result = run_r1(_tiny_tasks())
        # fairness condition: at equal base calibration, dominance is not a
        # base-distribution artifact
        assert result["ece_base"]["evidence"] < 0.15
        assert result["ece_base"]["verbalized"] < 0.15


class TestR2Verifiability:
    def test_default_workload_has_unverifiable_fraction(self):
        result = run_r2()
        assert result["fraction_unverifiable"] > 0.05
        assert result["default_escalate_fraction"] == result["fraction_unverifiable"]
        assert "recommendation" in result

    def test_audit_tasks(self):
        result = audit_tasks(generate_tasks(100, seed=5))
        assert 0.0 <= result["fraction_unverifiable"] <= 1.0
        assert result["n"] == 100

    def test_audit_seeds(self):
        from trust.gated_data.models import SeedRecord

        seeds = [
            SeedRecord("a", "text", True, "test", signal_kinds=["tool"]),
            SeedRecord("b", "text2", True, "test", signal_kinds=[]),
        ]
        result = audit_seeds(seeds)
        assert result["n_unverifiable"] == 1
        assert result["fraction_unverifiable"] == 0.5

    def test_artifacts_written(self, tmp_path):
        run_r2(out_dir=tmp_path)
        assert (tmp_path / "r2_verifiability.json").exists()
        assert (tmp_path / "r2_verifiability.png").exists()
