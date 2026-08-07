"""S3 — difficulty-model cross-validation and feature ablation.

Does our difficulty model actually predict human solvability? K-fold CV
over tasks: fit on train folds, measure rank correlation between fitted
difficulty and the oracle's measured solve rate on the held-out fold.
Then ablate feature sets: does n_calls / n_tools / arg_complexity each
carry signal?

The blog angle: the difficulty model is the 'measurement' between raw
tasks and the stratified benchmark — if it lies, the splits lie.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

from trust.forge.calibration import SimulatedOracle
from trust.forge.difficulty import DifficultyModel, task_features
from trust.forge.generators import DerivedArgTaskGenerator, ToolUseTaskGenerator
from trust.forge.study import spearman, write_json


def _cv_rank_correlation(tasks, oracle, k: int = 5, features: list[int] | None = None) -> float:
    """K-fold CV: fit on train, correlate fitted difficulty vs measured
    solve rate on test. Higher (more negative) = the model generalizes."""
    import random

    rng = random.Random(7)
    idx = list(range(len(tasks)))
    rng.shuffle(idx)
    folds = [idx[i::k] for i in range(k)]
    corrs = []
    for f in range(k):
        test_ids = set(folds[f])
        train = [t for i, t in enumerate(tasks) if i not in test_ids]
        test = [t for i, t in enumerate(tasks) if i in test_ids]
        outcomes = [oracle.calibrate(t) for t in train]
        model = DifficultyModel()
        model.feature_keys = ["n_calls", "n_tools", "arg_complexity"]
        # fit with selected features
        X = [[task_features(t)[j] for j in (features or [0, 1, 2])] for t in train]
        y = [o.n_solved / max(o.n_attempts, 1) for o in outcomes]
        model._fit_matrix(X, y)
        model._feature_cols = features or [0, 1, 2]
        pairs = []
        for t in test:
            o = oracle.calibrate(t)
            fx = [task_features(t)[j] for j in model._feature_cols]
            d = model._difficulty_from_features(fx)
            pairs.append((d, o.n_solved / max(o.n_attempts, 1)))
        pairs.sort(key=lambda p: p[0])
        corrs.append(spearman([p[0] for p in pairs], [p[1] for p in pairs]))
    return statistics.mean(corrs)


def run_all(out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks = ToolUseTaskGenerator().generate(n=200) + DerivedArgTaskGenerator().generate(n=30)
    oracle = SimulatedOracle()
    results: dict[str, Any] = {}

    # full feature set
    results["all_features"] = _cv_rank_correlation(tasks, oracle, features=[0, 1, 2])
    # ablations
    results["n_calls_only"] = _cv_rank_correlation(tasks, oracle, features=[0])
    results["n_tools_only"] = _cv_rank_correlation(tasks, oracle, features=[1])
    results["arg_complexity_only"] = _cv_rank_correlation(tasks, oracle, features=[2])
    results["n_calls_n_tools"] = _cv_rank_correlation(tasks, oracle, features=[0, 1])

    write_json(out_dir / "s3-difficulty-cv.json", results)
    print(json.dumps(results, indent=2))
    return results


if __name__ == "__main__":
    import argparse
    import sys

    p = argparse.ArgumentParser()
    p.add_argument("--out", default="docs/validation/studies")
    run_all(Path(p.parse_args().out))
    sys.exit(0)
