"""A-S-15 swarm-core: agents + world → trajectory ensemble, asyncio.

AI-Metropolis discipline (BUILD integrity rule 3) is enforced in the
presence engine; this economic swarm evaluates agents' full ensemble at
each tick (they react to the same world state), which is the training-time
parallelism analogue. Trajectories are deterministic given (seed, world,
agents) via the RNG registry.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from sim_shared.rng import RNGRegistry

from .agent import Agent, AgentProto
from .world import World


@dataclass
class Trajectory:
    run_id: str
    seed: int
    values: np.ndarray          # (steps,) aggregate series
    members: list[str] = field(default_factory=list)


def _make_agents(n: int, rule: Callable[[World, np.random.Generator], object]) -> list[Agent]:
    return [Agent(AgentProto(id=f"a{i}", rule=rule), role="firm") for i in range(n)]


class Swarm:
    """A population; `run` produces one trajectory with a fixed seed."""

    def __init__(self, world: World, agents: list[Agent], run_id: str = "run") -> None:
        self.world = world
        self.agents = agents
        self.run_id = run_id

    async def step_all(self, rng: np.random.Generator) -> list:
        loop = asyncio.get_event_loop()
        tasks = [loop.run_in_executor(None, lambda a=a: a.step(self.world, rng)) for a in self.agents]
        return await asyncio.gather(*tasks)

    def run(self, steps: int, seed: int, metric: Callable[[World], float] | None = None) -> Trajectory:
        """One trajectory: `steps` aggregated world states, deterministic in seed."""
        registry = RNGRegistry(seed)
        rng = registry.generator("swarm")
        metric = metric or (lambda w: w.macro.get("activity", 0.0))
        path: list[float] = []
        for _ in range(steps):
            decisions = asyncio.run(self.step_all(rng))
            for d in decisions:
                self.world.macro["activity"] = self.world.macro.get("activity", 0.0) + d.magnitude / max(1, len(self.agents))
            self.world.clock.tick()
            path.append(float(metric(self.world)))
        return Trajectory(run_id=self.run_id, seed=seed, values=np.array(path), members=[a.id for a in self.agents])


def run_trajectory(
    world: World,
    agents: list[Agent],
    steps: int,
    seed: int,
    metric: Callable[[World], float] | None = None,
) -> Trajectory:
    return Swarm(world, agents, run_id=f"r{seed}").run(steps, seed, metric)