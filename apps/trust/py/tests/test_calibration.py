"""Phase 2 — calibration loop: oracle, difficulty model, stratification.

Validation gates:
1. The simulated oracle recovers a known planted difficulty ordering
   (hard tasks solve less than easy tasks).
2. Difficulty-matching produces splits with near-identical difficulty
   distributions (low KL), and split-predictability holds for synthetic
   systems.
3. A deliberately mis-stratified split fails the predictability assertion.
"""
from __future__ import annotations

import pytest

from trust.forge.calibration import SimulatedOracle
from trust.forge.difficulty import DifficultyModel, human_action_baseline, task_features
from trust.forge.generators import ToolUseTaskGenerator
from trust.forge.stratify import (
    SplitSet,
    _bin_spearman,
    difficulty_distribution,
    difficulty_match_splits,
    split_distribution_kl,
    split_predictability,
    system_solve_rates,
)
from trust.forge.study import spearman


@pytest.fixture(scope="module")
def task_population():
    # 120+ tasks: split predictability needs enough tasks per difficulty
    # bin for stable means (the evals-as-scaling sample-size lesson)
    return ToolUseTaskGenerator().generate(n=120)


class TestSimulatedOracle:
    def test_recovers_planted_difficulty_ordering(self, task_population):
        oracle = SimulatedOracle()
        # split the population by difficulty_seed prior
        easy = sorted(task_population, key=lambda t: t.difficulty_seed)[:15]
        hard = sorted(task_population, key=lambda t: t.difficulty_seed)[-15:]
        easy_solve = mean_solve_rate(oracle, easy)
        hard_solve = mean_solve_rate(oracle, hard)
        assert easy_solve > hard_solve + 0.1, (easy_solve, hard_solve)

    def test_arc_2_of_10_bar(self, task_population):
        oracle = SimulatedOracle()
        outcomes = [oracle.calibrate(t) for t in task_population[:10]]
        for o in outcomes:
            assert o.n_attempts == 10
            assert o.n_solved <= 10
            if o.solved:
                assert o.n_solved >= 2
        assert any(o.solved for o in outcomes)  # the population has solvable tasks
        assert any(not o.solved for o in outcomes)  # and some too-hard ones

    def test_deterministic_per_task(self, task_population):
        oracle = SimulatedOracle()
        t = task_population[0]
        assert oracle.calibrate(t) == oracle.calibrate(t)

    def test_noise_scale_actually_changes_solve_probability_spread(self, task_population):
        """S1's sweep_oracle_noise study varies a `noise` parameter across
        5 values expecting different eval-quality numbers at each — but a
        prior version of SimulatedOracle had no noise parameter at all (a
        flat 0.05 was hardcoded), so every value in that sweep constructed
        an identical oracle and all 5 result rows were byte-identical.
        noise_scale=0.0 must be deterministic-clean (probability ==
        sigmoid(k(d0-d)) exactly); a large noise_scale must actually
        perturb it."""
        t = task_population[0]
        clean = SimulatedOracle(k=6.0, d0=0.5, noise_scale=0.0)
        noisy = SimulatedOracle(k=6.0, d0=0.5, noise_scale=0.4)
        p_clean = clean._solve_probability(t)
        p_noisy = noisy._solve_probability(t)
        assert p_clean != p_noisy

    def test_harder_tasks_take_more_actions(self, task_population):
        oracle = SimulatedOracle()
        easy = min(task_population[:10], key=lambda t: t.difficulty_seed)
        hard = max(task_population[:10], key=lambda t: t.difficulty_seed)
        easy_out = oracle.calibrate(easy)
        hard_out = oracle.calibrate(hard)
        if easy_out.action_counts and hard_out.action_counts:
            assert mean(easy_out.action_counts) <= mean(hard_out.action_counts) + 1

    def test_action_baseline_scales_with_task_trajectory_length(self, task_population):
        """RHAE's efficiency ratio (human baseline / agent actions) is only
        meaningful if the human baseline is grounded in how many actions the
        task actually needs. A flat, task-length-independent baseline (the
        old behavior) makes every task's ratio blow past the 1.15 cap for
        any solver, since real solvers' agent_actions is always close to
        len(task.expected) (2-5) while the old baseline was a flat 8-20 —
        collapsing RHAE to solve rate with zero efficiency signal. Two
        tasks of very different lengths, solved at similar difficulty,
        should show human action counts scaling with length, not flat."""
        oracle = SimulatedOracle()
        short = min(task_population, key=lambda t: len(t.expected))
        long = max(task_population, key=lambda t: len(t.expected))
        assert len(long.expected) > len(short.expected)
        short_out = oracle.calibrate(short, n_attempts=30)
        long_out = oracle.calibrate(long, n_attempts=30)
        assert short_out.action_counts and long_out.action_counts
        # the human baseline for the longer task must itself be longer —
        # not just "harder", but proportionally larger to the task's own
        # minimal path length, so h/a (a == len(expected) for a clean solve)
        # doesn't saturate the RHAE cap for every task uniformly.
        assert mean(long_out.action_counts) > mean(short_out.action_counts)
        # and the ratio to the task's own minimal length should be in a
        # plausible "some human overhead, not absurd" range, not an
        # arbitrary flat offset unrelated to the task.
        short_ratio = mean(short_out.action_counts) / len(short.expected)
        long_ratio = mean(long_out.action_counts) / len(long.expected)
        assert 0.9 <= short_ratio <= 2.5, short_ratio
        assert 0.9 <= long_ratio <= 2.5, long_ratio


class TestDifficultyModel:
    def test_fit_and_recover(self, task_population):
        oracle = SimulatedOracle()
        outcomes = [oracle.calibrate(t) for t in task_population]
        model = DifficultyModel().fit(task_population, outcomes)
        assert model.weights is not None
        assert len(model.weights) == 3
        # fitted difficulty should correlate with the generator's prior
        fitted = [model.difficulty(t) for t in task_population]
        prior = [t.difficulty_seed for t in task_population]
        assert spearman(fitted, prior) > 0.3

    def test_feature_vector(self, task_population):
        t = task_population[0]
        assert len(task_features(t)) == 3

    def test_human_action_baseline(self, task_population):
        oracle = SimulatedOracle()
        outcomes = [oracle.calibrate(t) for t in task_population[:5]]
        base = human_action_baseline(outcomes, task_population[0].task_id)
        assert base >= 0


class TestBinSpearman:
    def test_mismatched_lengths_still_bin_to_the_same_chunk_count(self):
        """The exact regression the audit found: two perfectly-correlated
        (monotone increasing) lists of DIFFERENT length, at n_bins=5,
        used to produce 5 chunks for one and 4 for the other — a length
        mismatch that _spearman's equal-length guard silently turned into
        0.0, reading as "no correlation" for data that's perfectly
        correlated. len(a)=10, len(b)=12 is the audit's own example."""
        a = [float(i) for i in range(10)]
        b = [float(i) for i in range(12)]
        corr = _bin_spearman(a, b, n_bins=5)
        assert corr > 0.9, corr

    def test_perfectly_correlated_equal_length_scores_near_one(self):
        a = [float(i) for i in range(20)]
        b = [float(i) * 2 for i in range(20)]
        assert _bin_spearman(a, b, n_bins=5) == pytest.approx(1.0)

    def test_small_populations_below_n_bins_still_compare(self):
        # fewer values than n_bins used to fall through to 0 chunks or a
        # length mismatch; both should now bin down to min(len(a), len(b)).
        a = [1.0, 2.0, 3.0]
        b = [10.0, 20.0, 30.0, 40.0]
        corr = _bin_spearman(a, b, n_bins=5)
        assert corr > 0.9, corr


class TestSplitDistributionKL:
    def test_maximally_mismatched_split_reports_high_kl_not_near_zero(self, task_population):
        """A prior version skipped any bin where the private fraction was
        0, even when the public fraction there was substantial — a maximally
        mismatched split (all public mass in bins private never touches)
        silently dropped every such term and reported a near-zero,
        "well matched" KL. An empty private split is the cleanest example:
        public has real mass in several bins, private has none anywhere,
        and that must score as strongly mismatched, not ~0."""
        oracle = SimulatedOracle()
        outcomes = [oracle.calibrate(t) for t in task_population]
        model = DifficultyModel().fit(task_population, outcomes)
        kl = split_distribution_kl(task_population, [], model)
        assert kl > 1.0, kl

    def test_well_matched_split_still_reports_low_kl(self, task_population):
        oracle = SimulatedOracle()
        outcomes = [oracle.calibrate(t) for t in task_population]
        model = DifficultyModel().fit(task_population, outcomes)
        splits = difficulty_match_splits(task_population, model)
        kl = split_distribution_kl(splits.public, splits.private, model)
        assert kl < 0.1, kl


class TestDifficultyMatchSplitsNBins:
    def test_n_bins_actually_changes_the_split(self, task_population):
        """S5's nested-CV study sweeps n_bins expecting it to change the
        actual stratification — but a prior version of
        difficulty_match_splits had no n_bins parameter at all (always the
        module's hardcoded N_BINS=5), so S5's grid only ever changed how
        the ACCEPTANCE TEST measured predictability, never how the split
        was actually built; half the tuning grid was tuning the ruler, not
        the thing being measured. n_bins=1 (everything in one bin, pure
        random split) must allocate differently than n_bins=5
        (difficulty-stratified) on a population with real difficulty
        spread."""
        oracle = SimulatedOracle()
        outcomes = [oracle.calibrate(t) for t in task_population]
        model = DifficultyModel().fit(task_population, outcomes)

        one_bin = difficulty_match_splits(task_population, model, n_bins=1, seed=1)
        five_bins = difficulty_match_splits(task_population, model, n_bins=5, seed=1)

        one_bin_ids = {t.task_id for t in one_bin.public}
        five_bin_ids = {t.task_id for t in five_bins.public}
        assert one_bin_ids != five_bin_ids


class TestStratification:
    def test_splits_are_difficulty_matched(self, task_population):
        oracle = SimulatedOracle()
        outcomes = [oracle.calibrate(t) for t in task_population]
        model = DifficultyModel().fit(task_population, outcomes)
        splits = difficulty_match_splits(task_population, model)
        kl = split_distribution_kl(splits.public, splits.private, model)
        assert kl < 0.1, f"KL too high: {kl}"

    def test_split_predictability_holds_for_synthetic_systems(self, task_population):
        oracle = SimulatedOracle()
        outcomes = [oracle.calibrate(t) for t in task_population]
        model = DifficultyModel().fit(task_population, outcomes)
        splits = difficulty_match_splits(task_population, model)
        systems = {}
        for ability in (0.3, 0.5, 0.7):
            systems[f"sys-{ability}"] = {
                "public": system_solve_rates(splits.public, ability, seed=1, model=model),
                "private": system_solve_rates(splits.private, ability, seed=2, model=model),
            }
        result = split_predictability(systems, min_correlation=0.8)
        assert result["passed"], result

    def test_mis_stratified_split_fails_predictability(self, task_population):
        """A deliberately bad split (all easy public, all hard private)
        must fail the predictability assertion. The median split is too
        mild — monotone rate curves still rank-correlate — so the bad
        split uses a hard threshold (public < 0.45, private >= 0.45)."""
        oracle = SimulatedOracle()
        outcomes = [oracle.calibrate(t) for t in task_population]
        model = DifficultyModel().fit(task_population, outcomes)
        bad = SplitSet(
            public=[t for t in task_population if t.difficulty_seed < 0.45],
            private=[t for t in task_population if t.difficulty_seed >= 0.45],
        )
        systems = {
            "sys": {
                "public": system_solve_rates(bad.public, 0.5, seed=1, model=model),
                "private": system_solve_rates(bad.private, 0.5, seed=2, model=model),
            }
        }
        result = split_predictability(systems, min_correlation=0.8)
        assert not result["passed"]


# -- helpers ---------------------------------------------------------------

def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def mean_solve_rate(oracle: SimulatedOracle, tasks) -> float:
    rates = [o.n_solved / o.n_attempts for o in (oracle.calibrate(t) for t in tasks)]
    return mean(rates)


# spearman() is imported from trust.forge.study (see imports above) rather
# than kept as a local copy, so this test file can't silently drift from
# the production tie-averaging fix.
