"""Judge-agreement metrics (mirrors packages/substrate/src/eval.ts + 02's eval_core).

Cohen's kappa and Krippendorff's alpha power the verdict-classifier
calibration loop: golden set with bad examples → agreement vs human labels
→ target high-80s-90s. Values verified against the canonical `krippendorff`
0.8.1 reference implementation.
"""
import pytest

from substrate_knowledge.core.metrics import cohens_kappa, krippendorff_alpha


class TestCohensKappa:
    def test_perfect(self):
        assert cohens_kappa(["a", "a", "b", "b"], ["a", "a", "b", "b"]) == 1.0

    def test_below_chance(self):
        assert cohens_kappa(["a", "b"], ["b", "a"]) == pytest.approx(-1.0)

    def test_validation(self):
        with pytest.raises(ValueError):
            cohens_kappa([], [])
        with pytest.raises(ValueError):
            cohens_kappa(["a"], ["a", "b"])


class TestKrippendorffAlpha:
    def test_reference_example(self):
        rater_rows = [
            [None, None, None, None, None, 3, 4, 1, 2, 1, 1, 3, 3, None, 3],
            [1, None, 2, 1, 3, 3, 4, 3, None, None, None, None, None, None, None],
            [None, None, 2, 1, 3, 4, 4, None, 2, 1, 1, 3, 3, None, 4],
        ]
        units = [[r[u] for r in rater_rows] for u in range(15)]
        assert krippendorff_alpha(units) == pytest.approx(0.691358, abs=1e-5)

    def test_perfect_and_validation(self):
        assert krippendorff_alpha([["a", "a"], ["b", "b"]]) == 1.0
        with pytest.raises(ValueError):
            krippendorff_alpha([])
        with pytest.raises(ValueError):
            krippendorff_alpha([["a"], ["a"]])
        with pytest.raises(ValueError):
            krippendorff_alpha([["a", "a"], ["a", "a"]])

    def test_missing_values(self):
        assert krippendorff_alpha([[None, "x", "x"], ["x", None, "x"], ["y", "y", None]]) == 1.0

    def test_disagreement_is_below_perfect(self):
        ratings = [["a", "b"], ["a", "b"], ["a", "a"], ["b", "b"]]
        assert krippendorff_alpha(ratings) < 1.0
        assert krippendorff_alpha(ratings) > 0.0
