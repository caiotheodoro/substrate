"""Benchmark runner — the concrete end-to-end execution.

Pipeline: generate tasks → gauntlet → calibrate (oracle) → fit difficulty
→ stratify splits → run solvers under the 5x action budget → RHAE score →
contamination monitor → publish docs/validation/ artifacts.

This is the thing that produces REAL numbers: every solver's per-task
action counts, per-level efficiency vs the human baseline, per-split
predictability, and the total benchmark score — the same quantities ARC
publishes, on our domain.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from trust.forge.agents import AgentRun, GreedySolver, PerfectSolver, RandomSolver, Solver
from trust.forge.calibration import SimulatedOracle
from trust.forge.difficulty import DifficultyModel
from trust.forge.forge import forge_tasks
from trust.forge.rhae import EnvironmentScore, score_environment, total_benchmark_score
from trust.forge.stratify import difficulty_match_splits, split_predictability, system_solve_rates
from trust.forge.task import ForgeTask


@dataclass
class BenchmarkRun:
    name: str
    seed: int
    tasks: list[ForgeTask] = field(default_factory=list)
    calibration: dict[str, dict[str, Any]] = field(default_factory=dict)
    difficulty: dict[str, float] = field(default_factory=dict)
    splits: dict[str, list[str]] = field(default_factory=dict)
    solver_runs: dict[str, list[AgentRun]] = field(default_factory=dict)
    scores: dict[str, dict[str, Any]] = field(default_factory=dict)
    contamination: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "seed": self.seed,
            "metadata": self.metadata,
            # n_tasks / n_scored: tasks that passed BOTH the gauntlet and the
            # 2-of-10 calibration bar — the only ones that get a difficulty
            # fit, a split assignment, and a score. n_gauntlet_survivors (in
            # metadata) is the pre-calibration count, kept distinct so
            # neither number is silently overloaded with the other's meaning.
            "n_tasks": len(self.tasks),
            "n_scored": len(self.difficulty),
            "calibration": {
                tid: {"n_solved": c["n_solved"], "n_attempts": c["n_attempts"], "solved": c["solved"]}
                for tid, c in self.calibration.items()
            },
            "difficulty": self.difficulty,
            "splits": {k: {"n": len(v)} for k, v in self.splits.items()},
            "solvers": {
                name: {
                    "solve_rate": round(sum(1 for r in runs if r.solved) / max(len(runs), 1), 4),
                    "mean_actions": round(sum(r.n_actions for r in runs) / max(len(runs), 1), 2),
                    "terminated": sum(1 for r in runs if r.terminated),
                }
                for name, runs in self.solver_runs.items()
            },
            "scores": {
                name: {
                    "total": round(s["total"], 4),
                    "environments": s.get("environments", []),
                }
                for name, s in self.scores.items()
            },
            "contamination": self.contamination,
        }

    def write(self, out_dir: Path) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"benchmark-{self.name}.json"
        path.write_text(json.dumps(self.as_dict(), indent=2))
        return path


def _external_corpus() -> list[str]:
    """Simulated external corpus (public web text, unrelated domains) —
    the honest contamination baseline. Matching THIS means the task
    content is in public training data."""
    return [
        "The quick brown fox jumps over the lazy dog and continues running across the meadow.",
        "PostgreSQL is an open source relational database management system emphasizing extensibility and SQL compliance.",
        "The Amazon rainforest produces roughly twenty percent of the world's oxygen and hosts immense biodiversity.",
        "Quantum entanglement describes a physical phenomenon where pairs of particles become correlated such that the state of one instantly influences the other.",
        "TypeScript is a typed superset of JavaScript that compiles to plain JavaScript for browser and server execution.",
        "The Great Barrier Reef is the world's largest coral reef system composed of over 2900 individual reefs and 900 islands.",
        "Machine learning is a field of study that gives computers the ability to learn without being explicitly programmed.",
        "The river Nile flows northward through northeastern Africa and is widely considered the longest river in the world.",
        "Rust is a multi-paradigm programming language designed for performance and safety, especially safe concurrency.",
        "Photosynthesis is the process used by plants and other organisms to convert light energy into chemical energy.",
    ]


def run_benchmark(
    *,
    name: str = "forge-agentic-tooluse",
    n_tasks: int = 120,
    seed: int = 7,
    solvers: list[Solver] | None = None,
    oracle: SimulatedOracle | None = None,
    generator: Callable[[], list[ForgeTask]] | None = None,
    min_pass_rate: float = 0.95,
    verbose: bool = True,
) -> BenchmarkRun:
    """Run the full benchmark pipeline. Returns a BenchmarkRun with all
    measured quantities; call .write() to publish artifacts."""
    from trust.forge.generators import ToolUseTaskGenerator

    log = lambda msg: print(f"[{name}] {msg}") if verbose else None  # noqa: E731

    # 1. generate + gauntlet
    log("generating + gauntlet")
    from trust.forge.generators import DerivedArgTaskGenerator, ToolUseTaskGenerator

    gen = generator
    if gen is None:
        base = ToolUseTaskGenerator().generate(n=n_tasks)
        derived_n = max(8, n_tasks // 4)
        derived = DerivedArgTaskGenerator().generate(n=derived_n)
        forged = forge_tasks(lambda: base + derived, min_pass_rate=min_pass_rate)
    else:
        forged = forge_tasks(gen, min_pass_rate=min_pass_rate)
    gauntlet_survivors = [t for t in forged.tasks if forged.gauntlet[t.task_id].passed]
    log(f"  survivors {len(gauntlet_survivors)}/{len(forged.tasks)} (gate {forged.pass_rate:.0%})")

    # 2. calibrate (P3: human oracle, ARC 2-of-10 bar)
    log("calibrating")
    oracle = oracle or SimulatedOracle()
    raw_outcomes = {t.task_id: oracle.calibrate(t) for t in gauntlet_survivors}
    outcomes = {tid: o.as_dict() for tid, o in raw_outcomes.items()}
    calibrated = [o for o in outcomes.values() if o["solved"]]
    log(f"  {len(calibrated)}/{len(gauntlet_survivors)} pass the 2-of-10 bar")

    # The 2-of-10 bar is not a diagnostic — tasks that fail it are rejected
    # from the benchmark entirely (ARC-AGI-3 §3: "difficulty is MEASURED,
    # never estimated"; a task nobody reliably solves twice isn't a
    # calibrated task, it's noise). Everything downstream — the difficulty
    # fit, the splits, the solver scoring — operates only on tasks that
    # passed. `calibration` in the artifact still reports every gauntlet
    # survivor's outcome (including rejects), so the rejection is visible;
    # `tasks`/`difficulty`/`scores` reflect only what actually got scored.
    tasks = [t for t in gauntlet_survivors if outcomes[t.task_id]["solved"]]

    # 3. difficulty model (P3) + splits (P4)
    log("fitting difficulty + stratifying")
    model = DifficultyModel().fit(tasks, [raw_outcomes[t.task_id] for t in tasks])
    difficulty = {t.task_id: model.difficulty(t) for t in tasks}
    splits = difficulty_match_splits(tasks, model, seed=seed)
    splits_map = {"public": [t.task_id for t in splits.public], "private": [t.task_id for t in splits.private]}
    log(f"  public {len(splits.public)} / private {len(splits.private)}")

    # 4. run solvers under the 5x action budget (P5)
    log("running solvers")
    solver_runs: dict[str, list[AgentRun]] = {}
    for solver in solvers or [RandomSolver(seed=seed), GreedySolver(), PerfectSolver()]:
        runs: list[AgentRun] = []
        for task in tasks:
            outcome = outcomes[task.task_id]
            # best (min) recorded human attempt, not an arbitrary first
            # attempt — matches rhae.py's own human_baseline_from_counts,
            # and falls back to the task's own minimal path length (not a
            # flat constant) since every task passed calibration here and
            # so always has at least 2 recorded solved attempts.
            baseline = min(outcome["action_counts"]) if outcome["action_counts"] else len(task.expected)
            budget = max(10, int(baseline * 5))
            runs.append(solver.solve(task, budget))
        solver_runs[solver.name] = runs
        sr = sum(1 for r in runs if r.solved) / max(len(runs), 1)
        log(f"  {solver.name}: solve rate {sr:.1%}")

    # 5. RHAE scoring (P5) — per task = one level; the human baseline is
    # the upper-median best across ALL calibrated humans on that task
    log("scoring")
    scores: dict[str, dict[str, Any]] = {}
    for solver_name, runs in solver_runs.items():
        env_scores: list[EnvironmentScore] = []
        for task, run in zip(tasks, runs):
            outcome = outcomes[task.task_id]
            # one level per task: all humans' action counts on that task
            human_counts = [outcome["action_counts"]] if outcome["action_counts"] else [[len(task.expected)]]
            agent = [run.n_actions] if run.solved else [0]
            env = score_environment(task.task_id, human_counts, agent)
            env_scores.append(env)
        total = total_benchmark_score(env_scores)
        scores[solver_name] = {"total": total, "environments": [e.as_dict() for e in env_scores]}
        log(f"  {solver_name}: RHAE {total:.3f}")

    # 6. split predictability (P4) — synthetic systems for the property test
    predictability = split_predictability(
        {
            "sys-0.3": {
                "public": system_solve_rates(splits.public, 0.3, seed, model),
                "private": system_solve_rates(splits.private, 0.3, seed + 1, model),
            },
            "sys-0.5": {
                "public": system_solve_rates(splits.public, 0.5, seed, model),
                "private": system_solve_rates(splits.private, 0.5, seed + 1, model),
            },
        }
    )

    # 7. contamination monitor (P7): leak probes against a knowledge base
    # built from a genuinely INDEPENDENT reference corpus (not the task
    # set's own signatures — that would make "fire on leaked" a tautology,
    # since a task's signature always matches a KB built from itself) +
    # corpus matching against an EXTERNAL text corpus (web-like text, not
    # the task set itself) + structural OOD between splits.
    log("contamination monitor")
    from trust.forge.contamination import build_reference_corpus, inject_leaks, leaked_knowledge_base, monitor_contamination

    reference_corpus = build_reference_corpus(max(20, len(tasks) // 5))
    contam_tasks, leaked_ids = inject_leaks(tasks, reference_corpus, fraction=0.1, seed=seed)
    kb = leaked_knowledge_base(reference_corpus)
    external_corpus = _external_corpus()
    contam = monitor_contamination(
        contam_tasks,
        public=splits.public,
        private=splits.private,
        knowledge_base=kb,
        leaked_ids=leaked_ids,
        corpus_texts=external_corpus,
    )
    contamination = contam.as_dict()
    log(f"  leaked-fire {contamination['leak_probe_fire_rate_on_leaked']} "
        f"clean-false-fire {contamination['leak_probe_false_fire_on_clean']} "
        f"structural-ood {contamination['structural_ood_overlap']}")

    return BenchmarkRun(
        name=name,
        seed=seed,
        tasks=tasks,
        calibration=outcomes,
        difficulty=difficulty,
        splits=splits_map,
        solver_runs=solver_runs,
        scores=scores,
        contamination=contamination,
        metadata={
            "n_generated": len(forged.tasks),
            "gauntlet_pass_rate": forged.pass_rate,
            "n_gauntlet_survivors": len(gauntlet_survivors),
            "n_calibrated": len(calibrated),
            "split_predictability": predictability,
        },
    )
