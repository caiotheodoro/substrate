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
        """Fractional (average) ranks: values tied for positions i..j all
        get the mean of those positions' ranks, not a sort-stable
        tiebreak by original index. Every headline correlation in this
        study harness (S1/S3/S6) runs on fitted difficulty values that are
        heavily tied in practice (13 distinct values across 120 tasks is
        typical) — an index-order tiebreak on that data is directional
        noise baked into the number, not a neutral simplification."""
        n = len(values)
        order = sorted(range(n), key=lambda i: values[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and values[order[j + 1]] == values[order[i]]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1  # 1-indexed mean of the tied block
            for k in range(i, j + 1):
                ranks[order[k]] = avg_rank
            i = j + 1
        return ranks

    ra, rb = rank(a), rank(b)
    n = len(a)
    if n < 2:
        return 0.0
    # The classic 1 - 6*sum(d^2)/(n(n^2-1)) shortcut is only algebraically
    # equivalent to "Pearson correlation of the ranks" when there are NO
    # ties (it's a simplification that relies on ranks being a permutation
    # of 1..n). With average-ranked ties that equivalence breaks — the
    # general, tie-correct definition of Spearman's rho is the direct
    # Pearson correlation of the (average) rank vectors, which is what
    # this computes and is what scipy's tie-corrected spearmanr matches.
    mean_ra = sum(ra) / n
    mean_rb = sum(rb) / n
    cov = sum((ra[i] - mean_ra) * (rb[i] - mean_rb) for i in range(n))
    var_a = sum((x - mean_ra) ** 2 for x in ra)
    var_b = sum((x - mean_rb) ** 2 for x in rb)
    denom = (var_a * var_b) ** 0.5
    return cov / denom if denom else 0.0


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
