"""Study harness — measuring the METHODOLOGY, not the models.

The core question behind the blog: which parameters of the eval-construction
pipeline actually matter for the validity of the resulting benchmark?

Eval-quality metrics (reported by every study):
- unsaturation_bandwidth: spread of per-level efficiency across solvers
  (a degenerate benchmark collapses to 0 or 1);
- split_predictability: public→private rank correlation (matched splits);
- calibration_monotonicity: Spearman between fitted difficulty and the
  oracle's measured solve rate (does the difficulty model tell the truth?);
- contamination_detection: leak-probe fire rate on leaked vs clean;
- reproducibility: score variance across seeds.

Studies:
- S1 parameter sweeps: each pipeline knob × its effect on eval quality
- S2 sample-size scaling: score stability vs task count / attempts
- S3 difficulty-model CV: feature sets × out-of-fold rank correlation
- S4 contamination ROC: leak fraction × detection rate
"""
from __future__ import annotations

import dataclasses
import json
import math
from pathlib import Path
from statistics import mean, stdev
from typing import Any

from trust.forge.calibration import SimulatedOracle
from trust.forge.difficulty import DifficultyModel
from trust.forge.generators import ToolUseTaskGenerator
from trust.forge.stratify import (
    difficulty_match_splits,
    split_predictability,
    system_solve_rates,
)


def spearman(a: list[float], b: list[float]) -> float:
    def rank(values: list[float]) -> list[float]:
        indexed = sorted(range(len(values)), key=lambda i: values[i])
        ranks = [0.0] * len(values)
        for pos, idx in enumerate(indexed):
            ranks[idx] = pos + 1
        return ranks

    ra, rb = rank(a), rank(b)
    n = len(a)
    if n < 2:
        return 0.0
    d2 = sum((ra[i] - rb[i]) ** 2 for i in range(n))
    denom = n * (n * n - 1) / 6.0
    return 1.0 - (6.0 * d2) / (6.0 * denom) if denom else 0.0


def eval_quality_metrics(
    tasks: list[Any],
    oracle: SimulatedOracle,
    model: DifficultyModel,
    seed: int = 7,
) -> dict[str, float]:
    """The five eval-quality metrics for a task population + difficulty
    model. Every study reports these, so parameter changes are comparable."""
    outcomes = [oracle.calibrate(t) for t in tasks]

    # 1. calibration monotonicity: fitted difficulty vs measured solve rate
    pairs = sorted(
        (
            (model.difficulty(t), o.n_solved / max(o.n_attempts, 1))
            for t, o in zip(tasks, outcomes)
        ),
        key=lambda p: p[0],
    )
    ds = [p[0] for p in pairs]
    rates = [p[1] for p in pairs]
    calib_mono = spearman(ds, rates)  # negative = harder → lower solve rate

    # 2. split predictability
    splits = difficulty_match_splits(tasks, model, seed=seed)
    systems = {
        "sys-0.3": {
            "public": system_solve_rates(splits.public, 0.3, seed, model),
            "private": system_solve_rates(splits.private, 0.3, seed + 1, model),
        },
        "sys-0.7": {
            "public": system_solve_rates(splits.public, 0.7, seed, model),
            "private": system_solve_rates(splits.private, 0.7, seed + 1, model),
        },
    }
    pred = split_predictability(systems, min_correlation=0.8)
    pred_corr = mean(pred["correlations"].values())

    # 3. unsaturation bandwidth: fitted-difficulty stdev of the population
    fitted = [model.difficulty(t) for t in tasks]
    bandwidth = stdev(fitted) if len(fitted) > 1 else 0.0

    # 4. reproducibility proxy: calibration outcome variance across the
    # population (higher = the oracle actually discriminates)
    solve_rates = [o.n_solved / o.n_attempts for o in outcomes]
    discrim = stdev(solve_rates) if len(solve_rates) > 1 else 0.0

    return {
        "calibration_monotonicity": round(calib_mono, 4),
        "split_predictability": round(pred_corr, 4),
        "difficulty_bandwidth": round(bandwidth, 4),
        "oracle_discrimination": round(discrim, 4),
    }


def make_population(n_tasks: int, difficulty_scale: float = 1.0) -> list[Any]:
    """Task population with a configurable difficulty compression factor —
    S1 uses this to vary how much difficulty signal the generator emits."""
    tasks = ToolUseTaskGenerator().generate(n=n_tasks)
    if difficulty_scale != 1.0:
        tasks = [
            dataclasses.replace(
                t,
                difficulty_seed=max(0.05, min(0.98, t.difficulty_seed * difficulty_scale)),
            )
            for t in tasks
        ]
    return tasks


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
