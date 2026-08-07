"""S6 — judge-ladder budget study: how much human calibration budget can a
pre-screening judge save without hurting calibration monotonicity?

Directly extends Airbnb's judge-calibration loop (build a golden dataset,
measure agreement with kappa/alpha, refine) + METR's sample-efficiency
framing — already applied to TASK COUNT in S2, here applied to per-task
ATTEMPT BUDGET. The question: if a calibrated judge pre-screens which
tasks are unambiguously easy or hard, how many of the 10 human attempts
per task can be skipped before the difficulty model starts lying?

Uses a REAL LLM (``MODEL_PROVIDER_*`` env vars) as the judge — not
simulated. Each task pays for exactly one real judge call regardless of
how many threshold values are swept (the sweep re-slices the same cached
estimate), so the study stays cheap even at real-API prices.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable

import httpx

from trust.forge.calibration import CalibrationOutcome, SimulatedOracle
from trust.forge.difficulty import DifficultyModel
from trust.forge.generators import ToolUseTaskGenerator
from trust.forge.study import spearman, write_json
from trust.forge.task import ForgeTask

N_ATTEMPTS = 10  # ARC's 2-of-10 bar — full human calibration cost per task
THRESHOLDS = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]  # 0.0 = judge screens nothing


def judge_difficulty_estimate_llm(base_url: str, model: str, api_key: str) -> Callable[[ForgeTask], float]:
    """Returns a judge_fn that asks a real LLM to rate a task's apparent
    difficulty from its prompt + tool list alone (no trajectory, no
    oracle). 0.5 (maximally uncertain) on any network/parse failure, so a
    broken judge can never silently inflate the reported budget savings."""

    def judge_fn(task: ForgeTask) -> float:
        tool_desc = "\n".join(f"- {t.name}: {t.description}" for t in task.tools)
        prompt = (
            f"Task: {task.prompt}\n\nAvailable tools:\n{tool_desc}\n\n"
            "Rate how difficult this task looks for an AI agent to solve, "
            "from 0.0 (trivial, one obvious tool call) to 1.0 (very hard, "
            "many non-obvious steps). Reply with ONLY a number between 0 and 1."
        )
        try:
            resp = httpx.post(
                f"{base_url}/chat/completions",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                    "max_tokens": 8,
                },
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=30,
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"]
            m = re.search(r"(\d*\.?\d+)", text)
            return max(0.0, min(1.0, float(m.group(1)))) if m else 0.5
        except Exception:
            return 0.5

    return judge_fn


def _auto_outcome(task: ForgeTask, judge_score: float) -> CalibrationOutcome:
    """A judge-screened task never sees a human: verdict is a clean binary
    label from the judge's own confident call (n_attempts=1 is nominal,
    for the solve-rate ratio the difficulty model fits on — the real
    attempt-budget accounting in run_sweep treats every auto-resolved task
    as costing 0 of its N_ATTEMPTS human budget)."""
    solved = judge_score < 0.5
    return CalibrationOutcome(
        task_id=task.task_id,
        n_attempts=1,
        n_solved=(1 if solved else 0),
        solve_time_s=0.0,
        action_counts=[],
    )


def run_sweep(
    tasks: list[ForgeTask],
    oracle: SimulatedOracle,
    judge_fn: Callable[[ForgeTask], float],
    thresholds: list[float] = THRESHOLDS,
) -> dict[str, Any]:
    """For each threshold t, tasks whose judge score falls in the confident
    tails [0, t) or (1-t, 1] are auto-resolved by the judge (0 human
    attempts); everything in the middle band gets full human calibration
    (10 attempts). t=0.0: the band is the whole [0,1] range, nothing is
    auto-resolved (full budget, today's SimulatedOracle-only behavior).
    t=0.5: the band collapses to the single point 0.5, so almost every
    task is auto-resolved. Ground truth (calibration_monotonicity's
    target) is always the FULL real oracle on every task, computed once —
    the judge is graded against it, never allowed to define its own
    truth."""
    ground_truth = {t.task_id: oracle.calibrate(t) for t in tasks}
    judge_scores = {t.task_id: judge_fn(t) for t in tasks}

    results: dict[str, Any] = {"thresholds": {}}
    for t_val in thresholds:
        lo, hi = t_val, 1.0 - t_val
        outcomes: dict[str, CalibrationOutcome] = {}
        n_auto = 0
        for task in tasks:
            js = judge_scores[task.task_id]
            if js < lo or js > hi:
                outcomes[task.task_id] = _auto_outcome(task, js)
                n_auto += 1
            else:
                outcomes[task.task_id] = ground_truth[task.task_id]

        model = DifficultyModel().fit(tasks, [outcomes[t.task_id] for t in tasks])
        pairs = sorted(
            (
                (model.difficulty(t), ground_truth[t.task_id].n_solved / max(ground_truth[t.task_id].n_attempts, 1))
                for t in tasks
            ),
            key=lambda p: p[0],
        )
        calib_mono = spearman([p[0] for p in pairs], [p[1] for p in pairs])

        n_human = len(tasks) - n_auto
        budget_used = n_human * N_ATTEMPTS  # auto-resolved tasks cost 0
        budget_total = N_ATTEMPTS * len(tasks)
        results["thresholds"][str(t_val)] = {
            "n_auto_resolved": n_auto,
            "n_human_calibrated": len(tasks) - n_auto,
            "attempt_budget_used": budget_used,
            "attempt_budget_fraction": round(budget_used / budget_total, 4),
            "calibration_monotonicity": round(calib_mono, 4),
        }
    results["judge_scores"] = {tid: round(s, 4) for tid, s in judge_scores.items()}
    return results


def run_all(out_dir: Path, *, n_tasks: int = 60) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks = ToolUseTaskGenerator().generate(n=n_tasks)
    oracle = SimulatedOracle()

    base_url = os.environ.get("MODEL_PROVIDER_BASE_URL", "http://localhost:11434") + "/v1"
    model = os.environ.get("MODEL_PROVIDER_MODEL_ID", "qwen2.5:3b")
    api_key = os.environ.get("MODEL_PROVIDER_API_KEY", "ollama")
    judge_fn = judge_difficulty_estimate_llm(base_url, model, api_key)

    results = run_sweep(tasks, oracle, judge_fn)
    write_json(out_dir / "s6-judge-ladder.json", results)
    print(json.dumps(results["thresholds"], indent=2))
    return results


if __name__ == "__main__":
    import argparse
    import sys

    p = argparse.ArgumentParser()
    p.add_argument("--out", default="docs/validation/studies")
    p.add_argument("--tasks", type=int, default=60)
    args = p.parse_args()
    run_all(Path(args.out), n_tasks=args.tasks)
    sys.exit(0)
