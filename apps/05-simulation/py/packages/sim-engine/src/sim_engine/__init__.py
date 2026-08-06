"""M4 — Simulation Engine (hybrid reference impl).

swarm-core (A-S-15), sim-world (A-S-16), agent-proto (A-S-17),
ensemble-store (A-S-18), simulator-adapter-sdk (A-S-19).
Mesa's reference semantics are implemented leanly with asyncio — the
dependency is deliberately absent (SPEC architecture sketch).
"""

from .world import Event, EventBus, Sector, SimulationClock, World
from .agent import Agent, AgentProto, Decision
from .swarm import Swarm, Trajectory, run_trajectory
from .ensemble_store import EnsembleRunResult, EnsembleStore
from .adapter_sdk import (
    EnsembleForecast,
    SimulatorAdapter,
    discover_entrypoints,
    get_adapter,
    list_adapters,
    register_adapter,
    remove_adapter,
)
from .swarm_demo import CascadeBehaviourAdapter

__all__ = [
    "Event",
    "EventBus",
    "Sector",
    "SimulationClock",
    "World",
    "Agent",
    "AgentProto",
    "Decision",
    "Swarm",
    "Trajectory",
    "run_trajectory",
    "EnsembleRunResult",
    "EnsembleStore",
    "EnsembleForecast",
    "SimulatorAdapter",
    "discover_entrypoints",
    "get_adapter",
    "list_adapters",
    "register_adapter",
    "remove_adapter",
    "CascadeBehaviourAdapter",
]