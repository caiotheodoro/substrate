"""Known-value tests for the shared eval core (mirrors eval.ts)."""
import pytest

from trust.eval_core import (
    bigrametric,
    brier_score,
    expected_calibration_error,
    ndcg_at_k,
    ndcg_escalation,
    reliability_coverage,
    shift_delta,
)


class TestBrier:
    def test_known_value(self):
        assert brier_score([1.0, 0.0, 1.0], [1, 0, 0]) == pytest.approx(1 / 3)

    def test_perfect(self):
        assert brier_score([1.0, 0.0], [1, 0]) == 0.0

    def test_length_mismatch(self):
        with pytest.raises(ValueError):
            brier_score([1.0], [1, 0])

    def test_empty(self):
        with pytest.raises(ValueError):
            brier_score([], [])


class TestEce:
    def test_known_value(self):
        # bins [0.2, 0.3): conf 0.2 x2, acc 0.5; [0.8, 0.9): conf 0.8 x2, acc 0.5
        ece, bins = expected_calibration_error([0.2, 0.2, 0.8, 0.8], [0, 1, 1, 0])
        assert ece == pytest.approx(0.3)
        assert sum(b.count for b in bins) == 4

    def test_perfect_calibration(self):
        ece, _ = expected_calibration_error([0.5, 0.5, 0.5, 0.5], [1, 0, 1, 0])
        assert ece == pytest.approx(0.0)

    def test_empty(self):
        with pytest.raises(ValueError):
            expected_calibration_error([], [])


class TestNdcg:
    def test_known_value(self):
        import math

        assert ndcg_at_k([1, 0, 0, 1], k=2, order=[0, 1, 2, 3]) == pytest.approx(1 / (1 + 1 / math.log2(3)))

    def test_perfect_order(self):
        assert ndcg_at_k([1, 0, 1], k=3, order=[2, 0, 1]) == pytest.approx(1.0)

    def test_escalation_descending(self):
        import math

        # eval_core primitive: rank by confidence desc (surprise diagnostic)
        assert ndcg_escalation([0.9, 0.6, 0.2], [0, 1, 1]) == pytest.approx(
            (0 + 1 / math.log2(3) + 1 / math.log2(4)) / (1 + 1 / math.log2(3))
        )


class TestCoverage:
    def test_coverage_fraction(self):
        assert reliability_coverage([0.5, 1.5], [0, 1], [1, 2], 0.9) == 1.0
        assert reliability_coverage([0.5, 5.0], [0, 1], [1, 2], 0.9) == 0.5

    def test_length_mismatch(self):
        with pytest.raises(ValueError):
            reliability_coverage([1], [0], [1, 2], 0.9)


class TestShiftDelta:
    def test_degradation_is_positive(self):
        base_c, base_y = [0.9, 0.9, 0.1, 0.1], [1, 1, 0, 0]
        shifted_c, shifted_y = [0.9, 0.9, 0.1, 0.1], [0, 0, 1, 1]
        d = shift_delta(base_c, shifted_c, base_y, shifted_y)
        assert d["brier_delta"] > 0
        assert d["ece_delta"] >= 0
        assert set(d) == {"brier_base", "brier_shifted", "brier_delta", "ece_base", "ece_shifted", "ece_delta"}


class TestReport:
    def test_bigrametric_fields(self):
        r = bigrametric([0.5, 0.5, 0.9], [1, 0, 1])
        assert r.brier >= 0 and r.ece >= 0
        assert len(r.bins) == 10


class TestJudgeAgreement:
    def test_cohens_kappa_perfect(self):
        from trust.eval_core import cohens_kappa

        assert cohens_kappa(["a", "a", "b", "b"], ["a", "a", "b", "b"]) == 1.0

    def test_cohens_kappa_below_chance(self):
        from trust.eval_core import cohens_kappa

        assert cohens_kappa(["a", "b"], ["b", "a"]) == pytest.approx(-1.0)

    def test_cohens_kappa_validation(self):
        from trust.eval_core import cohens_kappa

        with pytest.raises(ValueError):
            cohens_kappa([], [])
        with pytest.raises(ValueError):
            cohens_kappa(["a"], ["a", "b"])

    def test_krippendorff_alpha_reference_example(self):
        from trust.eval_core import krippendorff_alpha

        rater_rows = [
            [None, None, None, None, None, 3, 4, 1, 2, 1, 1, 3, 3, None, 3],
            [1, None, 2, 1, 3, 3, 4, 3, None, None, None, None, None, None, None],
            [None, None, 2, 1, 3, 4, 4, None, 2, 1, 1, 3, 3, None, 4],
        ]
        units = [[r[u] for r in rater_rows] for u in range(15)]
        assert krippendorff_alpha(units) == pytest.approx(0.691358, abs=1e-5)

    def test_krippendorff_alpha_perfect_and_validation(self):
        from trust.eval_core import krippendorff_alpha

        assert krippendorff_alpha([["a", "a"], ["b", "b"]]) == 1.0
        with pytest.raises(ValueError):
            krippendorff_alpha([])
        with pytest.raises(ValueError):
            krippendorff_alpha([["a"], ["a"]])
        with pytest.raises(ValueError):
            krippendorff_alpha([["a", "a"], ["a", "a"]])

    def test_krippendorff_alpha_missing_values(self):
        from trust.eval_core import krippendorff_alpha

        assert krippendorff_alpha([[None, "x", "x"], ["x", None, "x"], ["y", "y", None]]) == 1.0
