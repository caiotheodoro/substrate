"""P5 — RHAE efficiency scoring, ported exactly from ARC-AGI-3 §4.1.

The metric that keeps a benchmark unsaturated: score the test taker by
per-level relative action efficiency against a HUMAN baseline, squared,
capped, level-weighted, per-environment capped.

    S = min(1.15, h / a)^2            # per level (a = agent actions)
    E = min(sum(w_l)/sum(w), sum(w_l * S_l)/sum(w_l))   # per environment
    T = mean(E over environments)     # total benchmark score

Human baseline h = upper-median best first-run human action count
(ARC-AGI-3: the 3rd-place finisher among 4-5 completions). Levels are
weighted linearly (1/15..5/15 for 5 levels) so tutorial levels matter
least. Agents run under an action budget of 5x the human median.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import median
from typing import Any

PER_LEVEL_CAP = 1.15
ACTION_BUDGET_MULTIPLIER = 5.0


@dataclass
class LevelScore:
    level: int
    human_baseline: int
    agent_actions: int
    weight: float

    @property
    def efficiency(self) -> float:
        if self.agent_actions <= 0:
            return 0.0  # uncompleted level: no credit (the env cap also
            # enforces this, but per-level efficiency must not leak 1.15)
        if self.human_baseline <= 0:
            return 0.0
        ratio = min(PER_LEVEL_CAP, self.human_baseline / self.agent_actions)
        return ratio * ratio

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "human_baseline": self.human_baseline,
            "agent_actions": self.agent_actions,
            "weight": self.weight,
            "efficiency": round(self.efficiency, 4),
        }


@dataclass
class EnvironmentScore:
    environment_id: str
    levels: list[LevelScore] = field(default_factory=list)

    @property
    def n_levels(self) -> int:
        return len(self.levels)

    @property
    def score(self) -> float:
        """Weighted average of level scores, capped by the weighted
        fraction of levels completed (per-environment cap)."""
        if not self.levels:
            return 0.0
        total_w = sum(l.weight for l in self.levels)
        completed_w = sum(l.weight for l in self.levels if l.agent_actions > 0)
        efficiency_w = sum(l.weight * l.efficiency for l in self.levels)
        cap = completed_w / total_w if total_w else 0.0
        return min(cap, efficiency_w / total_w if total_w else 0.0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "environment_id": self.environment_id,
            "n_levels": self.n_levels,
            "score": round(self.score, 4),
            "levels": [l.as_dict() for l in self.levels],
        }


def linear_level_weights(n_levels: int) -> list[float]:
    """Linear level weights: level l (1-indexed) gets l / sum(1..n)."""
    total = n_levels * (n_levels + 1) / 2.0
    return [l / total for l in range(1, n_levels + 1)]


def human_baseline_from_counts(action_counts: list[list[int]]) -> int:
    """Upper-median best first-run human action count: for each human,
    take their best (min) action count; baseline = median of those minima."""
    bests = [min(counts) for counts in action_counts if counts]
    return int(median(bests)) if bests else 0


def score_environment(
    environment_id: str,
    human_action_counts: list[list[int]],
    agent_action_counts: list[int],
) -> EnvironmentScore:
    """Score one environment (one task = one level in ARC terms, but the
    formula is level-generic; for forge tasks each task is one level)."""
    n = len(human_action_counts)
    weights = linear_level_weights(n)
    levels: list[LevelScore] = []
    for i in range(n):
        baseline = human_baseline_from_counts([human_action_counts[i]])
        agent = agent_action_counts[i] if i < len(agent_action_counts) else 0
        levels.append(LevelScore(level=i + 1, human_baseline=baseline, agent_actions=agent, weight=weights[i]))
    return EnvironmentScore(environment_id=environment_id, levels=levels)


def total_benchmark_score(env_scores: list[EnvironmentScore]) -> float:
    if not env_scores:
        return 0.0
    return sum(e.score for e in env_scores) / len(env_scores)


def action_budget(human_median: int) -> int:
    """Agent action budget: 5x the human-baseline median (ARC-AGI-3 §4.3).
    Agents are terminated at this budget; the power-law decay makes the
    residual error negligible."""
    return int(math.ceil(human_median * ACTION_BUDGET_MULTIPLIER))
