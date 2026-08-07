"""S2 — sample-size scaling: how much eval is enough?

METR's evals-as-scaling question applied to benchmark construction:
benchmark score variance across random task SUBSETS vs task count. The
generator is deterministic, so seed variance is zero by construction —
the honest sampling-marginal is: draw k random subsets of size n from a
large population and measure score spread. The knee of that curve is
where the benchmark becomes trustworthy.
"""
from __future__ import annotations

import json
import random
import statistics
from pathlib import Path
from typing import Any

from trust.forge.agents import GreedySolver, PerfectSolver, RandomSolver
from trust.forge.benchmark import run_benchmark
from trust.forge.generators import DerivedArgTaskGenerator, ToolUseTaskGenerator


def _subset_score(tasks, subset_indices: list[int], seed: int) -> dict[str, float]:
    subset = [tasks[i] for i in subset_indices]

    def gen():
        return subset

    run = run_benchmark(
        name=f"subset-{seed}",
        n_tasks=len(subset),
        seed=seed,
        solvers=[RandomSolver(seed=seed), GreedySolver(), PerfectSolver()],
        generator=gen,
        verbose=False,
    )
    return {s: run.scores[s]["total"] for s in ("random", "greedy", "perfect")}


def run_all(out_dir: Path, repeats: int = 8) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pool = ToolUseTaskGenerator().generate(n=600)
    pool += DerivedArgTaskGenerator().generate(n=60)
    rng = random.Random(99)

    results: dict[str, Any] = {}
    for n in (30, 60, 120, 240, 480):
        scores = {"random": [], "greedy": [], "perfect": []}
        for rep in range(repeats):
            subset = rng.sample(range(len(pool)), min(n, len(pool)))
            got = _subset_score(pool, subset, seed=rep)
            for s in scores:
                scores[s].append(got[s])
        results[f"n{n}"] = {
            s: {
                "mean": round(statistics.mean(v), 4),
                "stdev": round(statistics.stdev(v), 4) if len(v) > 1 else 0.0,
                "min": round(min(v), 4),
                "max": round(max(v), 4),
            }
            for s, v in scores.items()
        }
        print(f"n={n}: greedy {results[f'n{n}']['greedy']['mean']} ± {results[f'n{n}']['greedy']['stdev']}")
    write_json(out_dir / "s2-sample-size.json", results)
    print(json.dumps(results, indent=2))
    return results


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


if __name__ == "__main__":
    import argparse
    import sys

    p = argparse.ArgumentParser()
    p.add_argument("--out", default="docs/validation/studies")
    p.add_argument("--repeats", type=int, default=8)
    run_all(Path(p.parse_args().out), p.parse_args().repeats)
    sys.exit(0)
