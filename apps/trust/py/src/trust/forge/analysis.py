"""Analysis of a benchmark run — the research artifact.

Produces docs/validation/analysis-<name>.json with:
- saturation evidence: per-solver score distribution, % of tasks at floor
  and ceiling (unsaturation = wide bandwidth, nothing at 0/1 in aggregate);
- per-solver efficiency breakdown: mean actions vs human baseline, waste
  ratio;
- difficulty calibration: measured solve rate vs fitted difficulty
  (the oracle is the truth; the model is the measurement);
- contamination summary: leak-probe fire rates, structural OOD;
- comparison against ARC-AGI-3's published numbers.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

from trust.forge.benchmark import BenchmarkRun


def analyze(run: BenchmarkRun) -> dict[str, Any]:
    scores = run.scores
    # len(run.difficulty), not len(run.tasks): the CLI path (main(), below)
    # reconstructs a BenchmarkRun from a saved artifact where the actual
    # ForgeTask objects aren't available, and deliberately passes
    # tasks=[] — len(run.tasks) silently reported 0 there. difficulty is
    # populated identically in both the live (run_benchmark) and
    # artifact-reconstructed paths, since it's keyed by task_id from JSON
    # either way.
    n = len(run.difficulty)

    # per-solver level-efficiency distributions (all environments)
    per_solver_eff: dict[str, list[float]] = {}
    per_solver_actions: dict[str, list[int]] = {}
    for name, s in scores.items():
        effs = [e["efficiency"] for env in s["environments"] for e in env["levels"]]
        acts = [e["agent_actions"] for env in s["environments"] for e in env["levels"]]
        per_solver_eff[name] = effs
        per_solver_actions[name] = acts

    # unsaturation: aggregate score should be strictly between 0 and 1 for
    # a non-degenerate solver; the distribution should have bandwidth
    bandwidth: dict[str, dict[str, Any]] = {}
    for name, effs in per_solver_eff.items():
        bandwidth[name] = {
            "mean": round(statistics.mean(effs), 4),
            "stdev": round(statistics.stdev(effs), 4) if len(effs) > 1 else 0.0,
            "pct_zero": round(sum(1 for e in effs if e == 0.0) / max(len(effs), 1), 4),
            "pct_capped": round(sum(1 for e in effs if e >= 1.3224) / max(len(effs), 1), 4),
        }

    # efficiency: actions vs human baseline
    efficiency: dict[str, dict[str, Any]] = {}
    for name, acts in per_solver_actions.items():
        solved_acts = [a for a in acts if a > 0]
        efficiency[name] = {
            "mean_actions_solved": round(statistics.mean(solved_acts), 2) if solved_acts else 0.0,
            "median_actions_solved": round(statistics.median(solved_acts), 2) if solved_acts else 0.0,
            "n_solved_levels": len(solved_acts),
        }

    # difficulty calibration: measured solve rate per difficulty decile
    # (from the artifact's calibration + difficulty maps)
    calib: list[dict[str, Any]] = []
    for task_id, o in run.calibration.items():
        calib.append(
            {
                "task": task_id,
                "difficulty": run.difficulty.get(task_id, 0.0),
                "solve_rate": o.get("n_solved", 0) / max(o.get("n_attempts", 10), 1),
            }
        )
    calib.sort(key=lambda c: c["difficulty"])
    deciles: list[dict[str, Any]] = []
    width = max(1, len(calib) // 10)
    for i in range(0, len(calib), width):
        chunk = calib[i : i + width]
        if not chunk:
            continue
        deciles.append(
            {
                "difficulty_mid": round(statistics.mean(c["difficulty"] for c in chunk), 3),
                "mean_solve_rate": round(statistics.mean(c["solve_rate"] for c in chunk), 3),
            }
        )

    return {
        "name": run.name,
        "seed": run.seed,
        "n_tasks": n,
        "metadata": run.metadata,
        "aggregate_scores": {k: round(v["total"], 4) for k, v in scores.items()},
        "unsaturation_bandwidth": bandwidth,
        "efficiency_vs_human": efficiency,
        "difficulty_calibration_deciles": deciles,
        "contamination": run.contamination,
        "arc_reference": {
            "note": "ARC-AGI-3 semi-private launch scores for reference",
            "opus_4_6": 0.005,
            "gemini_3_1": 0.004,
            "gpt_5_4": 0.002,
            "human": 1.0,
            "random_policy_floor": "1 in 10,000",
        },
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    p = argparse.ArgumentParser(description="analyze a benchmark artifact")
    p.add_argument("artifact", help="path to benchmark-<name>.json")
    args = p.parse_args(argv)

    data = json.loads(Path(args.artifact).read_text())
    # rebuild a light BenchmarkRun for analysis
    run = BenchmarkRun(
        name=data["name"],
        seed=data["seed"],
        tasks=[],
        calibration=data["calibration"],
        difficulty=data["difficulty"],
        splits=data["splits"],
        scores={name: {"total": s.get("total", s), "environments": s.get("environments", [])} for name, s in data["scores"].items()},
        contamination=data["contamination"],
        metadata=data["metadata"],
    )
    result = analyze(run)
    out = Path(args.artifact).with_name(f"analysis-{data['name']}.json")
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
