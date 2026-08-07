"""Study harness helpers.

Gate: spearman() must average-rank ties, not break them by sort-stable
index order. The repo's own fitted difficulty values are ~90% ties (13
distinct values across 120 tasks), and every S1/S3/S6 headline number goes
through this function — an untied estimator understates the correlation
on exactly the data this pipeline reports.
"""
from __future__ import annotations

import pytest

from trust.forge.study import spearman


class TestSpearmanTieCorrection:
    def test_no_ties_matches_untied_case(self):
        a = [1.0, 2.0, 3.0, 4.0, 5.0]
        b = [5.0, 4.0, 3.0, 2.0, 1.0]
        assert spearman(a, b) == pytest.approx(-1.0)

    def test_perfect_positive_correlation(self):
        a = [1.0, 2.0, 3.0, 4.0]
        b = [10.0, 20.0, 30.0, 40.0]
        assert spearman(a, b) == pytest.approx(1.0)

    def test_ties_are_average_ranked_not_index_ordered(self):
        """a has two tied values at positions 1,2 (both 2.0). An
        index-order tiebreak (rank 2, 3) vs average-rank (rank 2.5, 2.5)
        produce DIFFERENT correlations against a perfectly-monotone b —
        this is the actual bug: sort-stable tiebreaking is directional
        noise, not a neutral default, on data with many ties."""
        a = [1.0, 2.0, 2.0, 3.0]
        b = [1.0, 2.0, 3.0, 4.0]
        # rank(a) = [1, 2.5, 2.5, 4], rank(b) = [1, 2, 3, 4]. With ties,
        # Spearman's rho is the Pearson correlation of those rank vectors
        # directly (cross-checked against scipy.stats.spearmanr) — NOT the
        # 1 - 6*sum(d^2)/(n(n^2-1)) shortcut, which only equals that
        # Pearson correlation when ranks are an untied 1..n permutation.
        assert spearman(a, b) == pytest.approx(0.9486832980505139, abs=1e-9)

    def test_heavily_tied_data_matches_scipy_tie_corrected_spearman(self):
        """The concrete regression: data shaped like the repo's own fitted
        difficulty (a handful of distinct values repeated many times — 13
        distinct values across 120 tasks in practice). Cross-checked
        against scipy's tie-corrected implementation directly, not a
        hand-rolled comparison."""
        pytest.importorskip("scipy")
        from scipy.stats import spearmanr

        distinct = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3]
        a = [v for v in distinct for _ in range(9)]  # 117 values, heavy ties
        # not perfectly aligned with a's tie-break order, so a naive
        # index-order tiebreak and true tie-averaging actually diverge
        b = [(i * 37) % len(a) for i in range(len(a))]

        expected = spearmanr(a, b).statistic
        assert spearman(a, b) == pytest.approx(expected, abs=1e-9)
