"""A-S-17 agent-proto: decision rules + pluggable LLM augment.

An agent holds a persona, a deterministic decision rule, optional episodic
memory, and an OPTIONAL LLM augment. The augment is an OpenAI-compatible
client + a `prompt(strategy)` template — when absent the rule runs alone
(the reference implementations never depend on a running model).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

import numpy as np

from .world import World


@dataclass
class Decision:
    agent_id: str
    action: str
    magnitude: float
    reason: str = ""


@dataclass
class AgentProto:
    """Base agent contract. `decide` returns a Decision applied by the swarm."""

    id: str
    rule: Callable[[World, np.random.Generator], Decision]
    persona: dict[str, Any] = field(default_factory=dict)
    python_llm_augment: object | None = None  # optional OpenAI-compatible client

    def decide(self, world: World, rng: np.random.Generator) -> Decision:
        decision = self.rule(world, rng)
        if self.python_llm_augment is not None:
            decision.reason += f" | llm:({self._llm_hint(world)})"
        return decision

    def _llm_hint(self, world: World) -> str:
        return f"observe:{sorted(world.macro.keys())[:3]}" if world.macro else "no-macro"


class LLMAugment(Protocol):
    def augment(self, observation: dict) -> str: ...


class Agent:
    """Concrete swarm agent: persona + rule + optional augment (A-S-17)."""

    def __init__(self, proto: AgentProto, role: str = "actor") -> None:
        self.proto = proto
        self.role = role
        self.memory: list[dict] = []

    @property
    def id(self) -> str:
        return self.proto.id

    def step(self, world: World, rng: np.random.Generator) -> Decision:
        decision = self.proto.decide(world, rng)
        self.memory.append({"t": world.clock.now, "action": decision.action, "magnitude": decision.magnitude})
        return decision