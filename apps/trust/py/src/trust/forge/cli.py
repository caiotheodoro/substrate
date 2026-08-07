"""eval-bench CLI — run the Calibrated Evaluation Foundry benchmark.

Usage:
    uv run python -m trust.forge.cli bench --name agentic-tooluse --tasks 120 --seed 7
    uv run python -m trust.forge.cli bench --name agentic-tooluse --tasks 120 --seed 42

Publishes docs/validation/benchmark-<name>.json with all measured quantities:
gauntlet pass rate, calibration outcomes, difficulty, split predictability,
per-solver RHAE scores, contamination monitor.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from trust.forge.agents import GreedySolver, LlmSolver, PerfectSolver, RandomSolver
from trust.forge.benchmark import run_benchmark

DEFAULT_OUT = Path("docs/validation")


def _solvers(seed: int, args: argparse.Namespace) -> list:
    solvers = [RandomSolver(seed=seed), GreedySolver(), PerfectSolver()]
    if args.llm:
        import os

        api_key = args.llm_api_key or os.environ.get("MODEL_PROVIDER_API_KEY", "ollama")
        solvers.append(LlmSolver(base_url=args.llm_base, model=args.llm_model, api_key=api_key, name=args.llm_name))
    return solvers


def cmd_bench(args: argparse.Namespace) -> int:
    run = run_benchmark(
        name=args.name,
        n_tasks=args.tasks,
        seed=args.seed,
        solvers=_solvers(args.seed, args),
        verbose=True,
    )
    out = Path(args.out) / f"benchmark-{args.name}.json"
    run.write(Path(args.out))
    print(f"\nwrote {out}")
    print(json.dumps(run.as_dict()["scores"], indent=2))
    return 0


def cmd_matrix(args: argparse.Namespace) -> int:
    """Run the benchmark across multiple seeds — reproducibility evidence
    (the same numbers every time) and variance across populations."""
    results = []
    for seed in args.seeds:
        run = run_benchmark(name=f"{args.name}-s{seed}", n_tasks=args.tasks, seed=seed, solvers=_solvers(seed, args), verbose=False)
        results.append({"seed": seed, "scores": {k: round(v["total"], 4) for k, v in run.scores.items()}})
        run.write(Path(args.out))
    matrix_path = Path(args.out) / f"matrix-{args.name}.json"
    matrix_path.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
    print(f"\nwrote {matrix_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="eval-bench", description="Calibrated Evaluation Foundry benchmark CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("bench", help="run one benchmark")
    b.add_argument("--name", default="agentic-tooluse")
    b.add_argument("--tasks", type=int, default=120)
    b.add_argument("--seed", type=int, default=7)
    b.add_argument("--out", default=str(DEFAULT_OUT))
    b.add_argument("--llm", action="store_true", help="add the LLM solver (OpenAI-compatible endpoint required)")
    b.add_argument("--llm-base", default="http://localhost:11434/v1")
    b.add_argument("--llm-model", default="qwen2.5:3b")
    b.add_argument("--llm-api-key", default=None, help="falls back to $MODEL_PROVIDER_API_KEY, then 'ollama'")
    b.add_argument("--llm-name", default="llm", help="solver label in the artifact (e.g. 'llm-ollama', 'llm-deepseek')")
    b.set_defaults(fn=cmd_bench)

    m = sub.add_parser("matrix", help="run across seeds (reproducibility)")
    m.add_argument("--name", default="agentic-tooluse")
    m.add_argument("--tasks", type=int, default=120)
    m.add_argument("--seeds", type=int, nargs="+", default=[7, 11, 42])
    m.add_argument("--out", default=str(DEFAULT_OUT))
    m.add_argument("--llm", action="store_true")
    m.add_argument("--llm-base", default="http://localhost:11434/v1")
    m.add_argument("--llm-model", default="qwen2.5:3b")
    m.add_argument("--llm-api-key", default=None)
    m.add_argument("--llm-name", default="llm")
    m.set_defaults(fn=cmd_matrix)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
