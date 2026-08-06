"""A-T-11 shift-generator — perturbation transforms for the robustness axis.

Each transform is a pure function tasks -> tasks, deterministic under ``seed``.
The ConfBench robustness axis measures how a scorer's competencies degrade as
these transforms are applied.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

import numpy as np

from trust.confbench.tasks import ConfBenchTask

ShiftTransform = Callable[[list[ConfBenchTask], int], list[ConfBenchTask]]


@dataclass
class ShiftSpec:
    """Composable shift description — applied in order by ``apply_shift``."""

    difficulty_shift: float = 0.0
    self_report_inflation: float = 0.0
    retrieval_noise: float = 0.0
    tool_drop_rate: float = 0.0


def difficulty_skew(tasks: list[ConfBenchTask], amount: float, seed: int = 0) -> list[ConfBenchTask]:
    """Make the workload harder: difficulty rises, and the outcome is re-rolled
    under the base causal process with the observed evidence held fixed (the
    evidence stands; the outcome no longer does)."""
    rng = np.random.RandomState(seed)
    out: list[ConfBenchTask] = []
    for t in tasks:
        d = min(1.0, t.difficulty + amount)
        f = t.evidence.features
        z = (
            0.9 * f.get("tool_call_success", 0.0)
            + 0.9 * f.get("schema_satisfied", 0.0)
            + 0.6 * f.get("retrieval_kind_support", 0.0)
            + 0.8 * (f.get("outcomes_history_rate", 0.5) - 0.5)
            - 0.7 * f.get("tool_error", 0.0)
            - 2.0 * (d - 0.5)
            - 0.3
        )
        p_new = 1.0 / (1.0 + np.exp(-z))
        outcome = bool(rng.rand() < p_new)
        out.append(replace(t, difficulty=d, outcome=outcome))
    return out


def self_report_inflation(tasks: list[ConfBenchTask], amount: float, seed: int = 0) -> list[ConfBenchTask]:
    """Inflate the banned self-report channel on hard tasks — the model grows
    confident exactly where it fails. No production feature is affected."""
    rng = np.random.RandomState(seed)
    out: list[ConfBenchTask] = []
    for t in tasks:
        sr = {
            k: float(np.clip(v + amount * t.difficulty + rng.normal(0.0, 0.02), 0.02, 0.98))
            for k, v in t.self_report.items()
        }
        out.append(replace(t, self_report=sr))
    return out


def retrieval_noise(tasks: list[ConfBenchTask], std: float, seed: int = 0) -> list[ConfBenchTask]:
    """Degrade the retrieval channel: verdict probability becomes noisier and
    edges flip to silent — cheaper evidence stops being evidence."""
    rng = np.random.RandomState(seed)
    out: list[ConfBenchTask] = []
    for t in tasks:
        feats = dict(t.evidence.features)
        if feats.get("retrieval_prob", 0.0) > 0.0:
            noisy = float(np.clip(feats["retrieval_prob"] + rng.normal(0.0, std), 0.0, 1.0))
            feats["retrieval_prob"] = noisy
            if rng.rand() < std:
                for k in ("retrieval_kind_support", "retrieval_kind_contradict"):
                    feats[k] = 0.0
                feats["retrieval_kind_silent"] = 1.0
        out.append(replace(t, evidence=replace(t.evidence, features=feats)))
    return out


def tool_drop(tasks: list[ConfBenchTask], rate: float, seed: int = 0) -> list[ConfBenchTask]:
    """Some tool calls stop returning (toolchain outage): the tool channel
    degrades to ``not ran``."""
    rng = np.random.RandomState(seed)
    out: list[ConfBenchTask] = []
    for t in tasks:
        feats = dict(t.evidence.features)
        if feats.get("tool_call_ran", 0.0) == 1.0 and rng.rand() < rate:
            feats["tool_call_ran"] = 0.0
            feats["tool_call_success"] = 0.0
            feats["tool_result_sign_ok"] = 0.0
            feats["tool_result_schema_ok"] = 0.0
        out.append(replace(t, evidence=replace(t.evidence, features=feats)))
    return out


def apply_shift(tasks: list[ConfBenchTask], spec: ShiftSpec, seed: int = 0) -> list[ConfBenchTask]:
    """Compose the perturbation transforms (order: difficulty → retrieval →
    tool → self-report)."""
    rng = np.random.RandomState(seed)
    result = list(tasks)
    if spec.difficulty_shift:
        result = difficulty_skew(result, spec.difficulty_shift, seed)
    if spec.retrieval_noise:
        result = retrieval_noise(result, spec.retrieval_noise, seed)
    if spec.tool_drop_rate:
        result = tool_drop(result, spec.tool_drop_rate, seed)
    if spec.self_report_inflation:
        result = self_report_inflation(result, spec.self_report_inflation, seed + 1)
    return result


def shift_sweep(tasks: list[ConfBenchTask], amounts: list[float] = (0.1, 0.25, 0.5), seed: int = 0) -> dict[float, list[ConfBenchTask]]:
    """Difficulty-shift sweep for the shift-curve artifact."""
    return {a: apply_shift(tasks, ShiftSpec(difficulty_shift=a), seed) for a in amounts}
