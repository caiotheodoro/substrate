"""A-S-29 presence-llm: tiny+frontier policy with pruning hooks.

The cost-ceiling levers (SPEC): tiny model for routine moves, frontier only
for high-urgency/escalated moves, and pruning — an agent whose net urgency
is below the prune threshold never touches an LLM. Every choice flows
through the cost meter (A-S-35). The frontier model is env-key gated and
never a runtime dependency.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from sim_shared.cost import CostMeter

PRUNE_THRESHOLD = -0.25


@dataclass
class PresencePolicy:
    """Model selection + pruning for one presence room."""

    tiny_model: str = os.environ.get("SUBSTRATE_LLM_MODEL", "qwen2.5:0.5b")
    frontier_model: str = os.environ.get("SUBSTRATE_PEAK_MODEL", "")
    frontier_urgency: float = 1.2
    prune_threshold: float = PRUNE_THRESHOLD
    cost_meter: CostMeter | None = None

    def choose_model(self, urgency: float) -> str:
        """Tiny+frontier routing. The frontier is a PEAK (env-gated) model:
        when not configured, the policy degrades to the tiny model — frontier
        access is a peak-validation feature, never a runtime dependency."""
        if urgency >= self.frontier_urgency and self.frontier_model:
            return self.frontier_model
        return self.tiny_model

    def frontier_required(self, urgency: float) -> bool:
        """True when the move WOULD route to the frontier — callers use this
        to gate peak-validation runs behind SUBSTRATE_PEAK_*."""
        return urgency >= self.frontier_urgency

    def prune(self, agent) -> bool:
        """Pruning hook: skip LLM for agents with no real drive to act."""
        return agent.urgency() < self.prune_threshold

    def record_move(self, agent) -> str:
        model = self.choose_model(agent.urgency())
        if self.cost_meter is not None:
            self.cost_meter.record(
                agent_id=agent.id,
                round_idx=0,
                model=model,
                input_tokens=120,
                cached_input_tokens=0,
                output_tokens=60,
                latency_ms=400,
            )
        return model