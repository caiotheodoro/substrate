"""A-T-07 confbench-tasks — ground-truth tasks with verifiable artifacts.

Each task carries evidence features from the four allowed channels
(tool / retrieval / schema / outcome) plus a *banned* self-report channel
(logprob, self-consistency, verbalized) used only by the A-T-12 baselines.

The synthetic generator controls difficulty and the shift exposure so the R1
dominance question can be asked on the ConfBench distribution itself. The
generative model is deliberately simple: correctness depends on a latent
``v`` and task difficulty ``d``; evidence features are noisy monotone
encodings of both, while the self-report channel sees only ``v`` — a model
cannot report uncertainty about difficulty it cannot perceive.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from trust.evidence_features import EvidenceFeatures

TaskKind = Literal["tool", "retrieval", "schema", "outcome"]

BANNED_FEATURE_KEYS = ("logprob_norm", "self_consistency", "verbalized")


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


@dataclass(frozen=True)
class ConfBenchTask:
    """One ground-truth decision with all evidence channels materialized."""

    task_id: str
    kind: TaskKind
    difficulty: float
    latent_v: float
    evidence: EvidenceFeatures
    self_report: dict[str, float]
    outcome: bool
    source: str = "synthetic"

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "kind": self.kind,
            "difficulty": self.difficulty,
            "latent_v": self.latent_v,
            "evidence": self.evidence.to_row(),
            "self_report": self.self_report,
            "outcome": self.outcome,
            "source": self.source,
        }

    @property
    def checkable(self) -> bool:
        f = self.evidence.features
        return bool(
            f.get("tool_call_ran", 0.0) == 1.0
            or f.get("retrieval_kind_support", 0.0) == 1.0
            or f.get("retrieval_kind_contradict", 0.0) == 1.0
            or f.get("retrieval_kind_silent", 0.0) == 1.0
            or f.get("schema_satisfied", 0.0) == 1.0
            or f.get("schema_violation_missing", 0.0) == 1.0
            or f.get("schema_violation_type", 0.0) == 1.0
            or f.get("schema_violation_enum", 0.0) == 1.0
        )


def generate_tasks(n: int, seed: int = 42, *, shift: bool = False) -> list[ConfBenchTask]:
    """Synthetic ConfBench tasks (A-T-07).

    Generative model (difficulty-controlled, deterministic under ``seed``):

    - ``v`` latent quality ~ N(0, 1); ``d`` difficulty ~ U(0, 1).
    - Evidence features are noisy monotone encodings of ``(v, d_eff)`` —
      tool success, schema satisfaction, retrieval support and outcome
      history all degrade with difficulty.
    - Outcome: ``z = 0.9·tool_success + 0.9·schema_satisfied +
      0.6·retrieval_support + 0.8·(history − 0.5) − 0.7·tool_error −
      d_coef·(d_eff − 0.5) − 0.3``, ``y ~ Bernoulli(sigmoid(z))``. On base
      ``d_coef = 2``; under shift ``d_coef = 3`` and
      ``d_eff = min(1, d + 0.35)`` — hard tasks fail much harder under novel
      conditions.
    - Self-report (BANNED channel): a function of latent quality only,
      ``sigmoid(1.5·v)`` — it cannot report difficulty it cannot perceive.
      Under shift its noise scales with difficulty (``0.9·d_eff``): on novel
      hard inputs the model's internal probabilities decouple from
      correctness.
    """
    rng = np.random.RandomState(seed)
    v = rng.normal(size=n)
    d = rng.rand(n)
    d_eff = np.minimum(1.0, d + 0.35) if shift else d
    d_coef = 3.0 if shift else 2.0

    tool_ran = rng.rand(n) < 0.8
    tool_error = rng.rand(n) < _sigmoid(-1.2 * v + 1.4 * d_eff - 0.3)
    result_sign_ok = rng.rand(n) < _sigmoid(1.2 * v)
    result_schema_ok = rng.rand(n) < _sigmoid(1.2 * v - 1.0 * d_eff + 0.3)
    ret_prob = np.clip(_sigmoid(1.2 * v - 0.8 * d_eff) + rng.normal(0.0, 0.05, n), 0.0, 1.0)
    schema_satisfied = rng.rand(n) < _sigmoid(1.2 * v - 1.2 * d_eff + 0.4)
    schema_viol_missing = rng.rand(n) < _sigmoid(-1.2 * v - 1.0 * d_eff + 0.2)
    schema_viol_type = rng.rand(n) < _sigmoid(-1.2 * v - 0.8 * d_eff + 0.1)
    schema_viol_enum = rng.rand(n) < _sigmoid(-1.0 * v - 0.8 * d_eff + 0.05)
    history_rate = np.clip(_sigmoid(1.2 * v - 1.0 * d_eff) + rng.normal(0.0, 0.03, n), 0.02, 0.98)
    history_n = rng.randint(20, 200, size=n)
    recent_rate = np.clip(history_rate + rng.normal(0.0, 0.05, n), 0.02, 0.98)

    tool_success = tool_ran & ~tool_error
    ret_support = ret_prob > 0.55
    z = (
        0.9 * tool_success
        + 0.9 * schema_satisfied
        + 0.6 * ret_support
        + 0.8 * (history_rate - 0.5)
        - 0.7 * tool_error
        - d_coef * (d_eff - 0.5)
        - 0.3
    )
    p_out = _sigmoid(z)
    outcome = rng.rand(n) < p_out

    noise = 0.9 * d_eff if shift else 0.0
    verbalized = np.clip(_sigmoid(1.5 * v) + rng.normal(0.0, 0.04 + noise, n), 0.02, 0.98)
    logprob_norm = np.clip(_sigmoid(1.5 * v) + rng.normal(0.0, 0.05 + noise, n), 0.02, 0.98)
    self_consistency = np.clip(_sigmoid(1.5 * v) + rng.normal(0.0, 0.06 + noise, n), 0.02, 0.98)

    kinds = ["tool", "retrieval", "schema", "outcome"]
    tasks: list[ConfBenchTask] = []
    for i in range(n):
        feats = {
            "tool_call_ran": 1.0 if tool_ran[i] else 0.0,
            "tool_call_success": 0.0 if tool_error[i] else (1.0 if tool_ran[i] else 0.0),
            "tool_result_sign_ok": 1.0 if result_sign_ok[i] else 0.0,
            "tool_result_schema_ok": 1.0 if result_schema_ok[i] else 0.0,
            "tool_error": 1.0 if tool_error[i] else 0.0,
            "retrieval_kind_support": 1.0 if ret_prob[i] > 0.55 else 0.0,
            "retrieval_kind_contradict": 1.0 if ret_prob[i] < 0.45 else 0.0,
            "retrieval_kind_silent": 1.0 if 0.45 <= ret_prob[i] <= 0.55 else 0.0,
            "retrieval_prob": float(ret_prob[i]),
            "schema_satisfied": 1.0 if schema_satisfied[i] else 0.0,
            "schema_violation_missing": 1.0 if schema_viol_missing[i] else 0.0,
            "schema_violation_type": 1.0 if schema_viol_type[i] else 0.0,
            "schema_violation_enum": 1.0 if schema_viol_enum[i] else 0.0,
            "outcomes_history_rate": float(history_rate[i]),
            "outcomes_history_n": float(history_n[i]),
            "outcomes_recent_rate": float(recent_rate[i]),
        }
        tasks.append(
            ConfBenchTask(
                task_id=f"cb-{seed}-{i:05d}",
                kind=kinds[i % 4],
                difficulty=float(d[i]),
                latent_v=float(v[i]),
                evidence=EvidenceFeatures(feats),
                self_report={
                    "logprob_norm": float(logprob_norm[i]),
                    "self_consistency": float(self_consistency[i]),
                    "verbalized": float(verbalized[i]),
                },
                outcome=bool(outcome[i]),
            )
        )
    return tasks


def load_confbench_tasks() -> dict[str, list[ConfBenchTask]]:
    """Canonical ConfBench split (fixed seeds, deterministic): training set,
    base-holdout evaluation set, and shifted evaluation set."""
    return {
        "train": generate_tasks(800, seed=101),
        "base_eval": generate_tasks(400, seed=202),
        "shifted_eval": generate_tasks(400, seed=303, shift=True),
    }


def to_training_frame(tasks: list[ConfBenchTask]) -> tuple[list[dict[str, float]], list[bool]]:
    features = [t.evidence.to_row() for t in tasks]
    labels = [t.outcome for t in tasks]
    return features, labels


def from_frame_to_dicts(features: list[dict[str, float]], labels: list[bool]) -> list[dict[str, Any]]:
    return [{"features": f, "outcome": y} for f, y in zip(features, labels)]


def _cli_main() -> None:
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(prog="confbench-tasks", description="A-T-07: export the canonical ConfBench training frame as jsonl")
    parser.add_argument("--export-train", help="path to write the training jsonl (features + outcome per line)")
    args = parser.parse_args()
    if args.export_train:
        features, labels = to_training_frame(load_confbench_tasks()["train"])
        Path(args.export_train).parent.mkdir(parents=True, exist_ok=True)
        with Path(args.export_train).open("w") as fh:
            for row in from_frame_to_dicts(features, labels):
                fh.write(json.dumps(row) + "\n")


if __name__ == "__main__":
    _cli_main()
