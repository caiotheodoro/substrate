"""S1 — parameter sweeps: which pipeline knobs are load-bearing?

For each parameter, sweep its value and measure the eval-quality metrics.
A parameter is LOAD-BEARING if eval quality moves materially with it;
COSMETIC if flat. This is the empirical core of the blog: the Foundry's
knobs were inherited (ARC's 1/10,000, 2-of-10) — here we test whether
they matter, on our own domain.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trust.forge.calibration import SimulatedOracle
from trust.forge.difficulty import DifficultyModel
from trust.forge.study import eval_quality_metrics, make_population, write_json


def sweep_difficulty_scale(out_dir: Path) -> dict[str, Any]:
    """The generator's difficulty prior is compressed/spread by a factor.
    Too compressed → all tasks same difficulty → no calibration signal.
    Too spread → most tasks trivial or impossible."""
    results = {}
    for scale in (0.1, 0.3, 0.6, 1.0, 1.5, 2.0):
        tasks = make_population(120, difficulty_scale=scale)
        oracle = SimulatedOracle()
        outcomes = [oracle.calibrate(t) for t in tasks]
        model = DifficultyModel().fit(tasks, outcomes)
        results[str(scale)] = eval_quality_metrics(tasks, oracle, model)
    write_json(out_dir / "s1-difficulty-scale.json", results)
    return results


def sweep_oracle_noise(out_dir: Path) -> dict[str, Any]:
    """Human calibration noise (aleatoric): the oracle's per-task noise
    magnitude, actually varied via SimulatedOracle's noise_scale (a prior
    version constructed an identical oracle at every swept value here,
    since SimulatedOracle had no noise parameter to vary at all — this
    sweep measured nothing). Too noisy → calibration meaningless; too
    clean → unrealistic."""
    results = {}
    for noise in (0.0, 0.02, 0.05, 0.1, 0.2):
        tasks = make_population(120)
        oracle = SimulatedOracle(k=6.0, d0=0.5, noise_scale=noise)
        outcomes = [oracle.calibrate(t) for t in tasks]
        model = DifficultyModel().fit(tasks, outcomes)
        metrics = eval_quality_metrics(tasks, oracle, model)
        metrics["noise"] = noise
        results[str(noise)] = metrics
    write_json(out_dir / "s1-oracle-noise.json", results)
    return results


def sweep_population_skill(out_dir: Path) -> dict[str, Any]:
    """The human population's skill (d0): too skilled → everything passes
    the 2-of-10 bar; too weak → nothing does. ARC's selection bar assumes
    a Goldilocks zone."""
    results = {}
    for d0 in (0.2, 0.35, 0.5, 0.65, 0.8):
        tasks = make_population(120)
        oracle = SimulatedOracle(k=6.0, d0=d0)
        outcomes = [oracle.calibrate(t) for t in tasks]
        model = DifficultyModel().fit(tasks, outcomes)
        metrics = eval_quality_metrics(tasks, oracle, model)
        metrics["pass_rate"] = round(sum(1 for o in outcomes if o.solved) / len(outcomes), 3)
        results[str(d0)] = metrics
    write_json(out_dir / "s1-population-skill.json", results)
    return results


def sweep_n_tasks(out_dir: Path) -> dict[str, Any]:
    """Task population size: the sample-size scaling question. Too few →
    noisy predictability; the knee is where the benchmark becomes stable."""
    results = {}
    for n in (30, 60, 120, 240, 480):
        tasks = make_population(n)
        oracle = SimulatedOracle()
        outcomes = [oracle.calibrate(t) for t in tasks]
        model = DifficultyModel().fit(tasks, outcomes)
        metrics = eval_quality_metrics(tasks, oracle, model)
        metrics["n_tasks"] = n
        results[str(n)] = metrics
    write_json(out_dir / "s1-n-tasks.json", results)
    return results


def run_all(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {
        "difficulty_scale": sweep_difficulty_scale(out_dir),
        "oracle_noise": sweep_oracle_noise(out_dir),
        "population_skill": sweep_population_skill(out_dir),
        "n_tasks": sweep_n_tasks(out_dir),
    }
    write_json(out_dir / "s1-summary.json", results)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    import argparse
    import sys

    p = argparse.ArgumentParser()
    p.add_argument("--out", default="docs/validation/studies")
    run_all(Path(p.parse_args().out))
    sys.exit(0)
