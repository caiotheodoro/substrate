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
    difficulty_distribution,
    difficulty_match_splits,
    split_distribution_kl,
    split_predictability,
    system_solve_rates,
)


@pytest.fixture(scope="module")
def task_population():
    return ToolUseTaskGenerator().generate(n=60)


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

    def test_harder_tasks_take_more_actions(self, task_population):
        oracle = SimulatedOracle()
        easy = min(task_population[:10], key=lambda t: t.difficulty_seed)
        hard = max(task_population[:10], key=lambda t: t.difficulty_seed)
        easy_out = oracle.calibrate(easy)
        hard_out = oracle.calibrate(hard)
        if easy_out.action_counts and hard_out.action_counts:
            assert mean(easy_out.action_counts) <= mean(hard_out.action_counts) + 1


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
        must fail the predictability assertion."""
        oracle = SimulatedOracle()
        outcomes = [oracle.calibrate(t) for t in task_population]
        model = DifficultyModel().fit(task_population, outcomes)
        ordered = sorted(task_population, key=lambda t: t.difficulty_seed)
        mid = len(ordered) // 2
        bad = SplitSet(public=ordered[:mid], private=ordered[mid:])
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


def spearman(a: list[float], b: list[float]) -> float:
    def rank(values: list[float]) -> list[float]:
        indexed = sorted(range(len(values)), key=lambda i: values[i])
        ranks = [0.0] * len(values)
        for pos, idx in enumerate(indexed):
            ranks[idx] = pos + 1
        return ranks

    ra, rb = rank(a), rank(b)
    n = len(a)
    d2 = sum((ra[i] - rb[i]) ** 2 for i in range(n))
    denom = n * (n * n - 1) / 6.0
    return 1.0 - (6.0 * d2) / (6.0 * denom) if denom else 0.0
