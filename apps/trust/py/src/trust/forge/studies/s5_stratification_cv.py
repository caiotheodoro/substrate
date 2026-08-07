"""S5 — nested cross-validation for benchmark construction.

The protocol question: when you tune stratification hyperparameters
(n_bins, private_fraction) on one task population, does the tuning
generalize to a held-out population? Nested CV:

  outer loop: split the task pool into train-fold / test-fold populations
  inner loop: on train-fold, try (n_bins, private_fraction) grid, pick the
              config that maximizes split predictability
  validate:   apply the chosen config to test-fold, measure whether the
              predictability hold improves over the hand-set default

If tuned-params beat the default on held-out folds, the protocol works
and benchmark builders should tune. If not, the default is fine and
tuning is overfitting the construction.
"""
from __future__ import annotations

import itertools
import json
import random
from pathlib import Path
from typing import Any

from trust.forge.calibration import SimulatedOracle
from trust.forge.difficulty import DifficultyModel
from trust.forge.generators import DerivedArgTaskGenerator, ToolUseTaskGenerator
from trust.forge.stratify import difficulty_match_splits, split_predictability, system_solve_rates
from trust.forge.study import write_json


def _predictability_for(tasks, model, n_bins: int, private_fraction: float, seed: int) -> float:
    """Split predictability for a given stratification config. n_bins
    must reach BOTH the split construction and the acceptance test's own
    binning — a prior version only passed it to the latter, so tuning
    n_bins never actually changed how tasks were stratified, only how the
    (unchanged) split was measured."""
    splits = difficulty_match_splits(tasks, model, private_fraction=private_fraction, seed=seed, n_bins=n_bins)
    systems = {
        f"sys-{a}": {
            "public": system_solve_rates(splits.public, a, seed, model),
            "private": system_solve_rates(splits.private, a, seed + 1, model),
        }
        for a in (0.3, 0.7)
    }
    return split_predictability(systems, n_bins=n_bins)["correlations"]["sys-0.3"]


def _grid() -> list[dict[str, Any]]:
    return [
        {"n_bins": b, "private_fraction": f}
        for b, f in itertools.product((3, 5, 8), (0.3, 0.5, 0.7))
    ]


def run_all(out_dir: Path, k_outer: int = 4) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pool = ToolUseTaskGenerator().generate(n=480) + DerivedArgTaskGenerator().generate(n=60)
    oracle = SimulatedOracle()
    outcomes = {t.task_id: oracle.calibrate(t) for t in pool}
    model = DifficultyModel().fit(pool, [oracle.calibrate(t) for t in pool])

    rng = random.Random(5)
    idx = list(range(len(pool)))
    rng.shuffle(idx)
    folds = [idx[i::k_outer] for i in range(k_outer)]

    results: dict[str, Any] = {"folds": [], "summary": {}}
    default_scores = []
    tuned_scores = []
    for f in range(k_outer):
        test_idx = set(folds[f])
        train = [t for i, t in enumerate(pool) if i not in test_idx]
        test = [t for i, t in enumerate(pool) if i in test_idx]
        train_model = DifficultyModel().fit(train, [oracle.calibrate(t) for t in train])

        # inner loop: tune on train-fold
        best = None
        best_score = -1.0
        for cfg in _grid():
            s = _predictability_for(train, train_model, cfg["n_bins"], cfg["private_fraction"], seed=f)
            if s > best_score:
                best_score, best = s, cfg

        # default config (the hand-set baseline)
        default = _predictability_for(test, train_model, 5, 0.5, seed=f)
        tuned = _predictability_for(test, train_model, best["n_bins"], best["private_fraction"], seed=f)
        default_scores.append(default)
        tuned_scores.append(tuned)

        results["folds"].append(
            {
                "fold": f,
                "tuned_config": best,
                "train_predictability": round(best_score, 4),
                "default_test_predictability": round(default, 4),
                "tuned_test_predictability": round(tuned, 4),
                "tuned_wins": tuned > default,
            }
        )
        print(f"fold {f}: default {default:.3f} vs tuned {tuned:.3f} (cfg {best})")

    results["summary"] = {
        "mean_default": round(sum(default_scores) / len(default_scores), 4),
        "mean_tuned": round(sum(tuned_scores) / len(tuned_scores), 4),
        "tuned_wins_folds": sum(1 for f in results["folds"] if f["tuned_wins"]),
        "n_folds": k_outer,
    }
    write_json(out_dir / "s5-stratification-cv.json", results)
    print(json.dumps(results["summary"], indent=2))
    return results


if __name__ == "__main__":
    import argparse
    import sys

    p = argparse.ArgumentParser()
    p.add_argument("--out", default="docs/validation/studies")
    run_all(Path(p.parse_args().out))
    sys.exit(0)
