"""A-S-26 presence-core: urgency heap, NO global scheduler.

The room's only rule: the next mover is the agent with the highest urgency.
Order is recomputed every tick from the priority queue. An agent that is
pressured but inhibited produces a `silence` event — silence is behavior,
not absence (SPEC: pressure/inhibition is the mechanism that makes silence
meaningful).
"""

from __future__ import annotations

import asyncio
import heapq
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from sim_shared.rng import RNGRegistry

from .affect_models import CircumplexState
from .social_log import SocialLog

DEFAULT_SILENCE_THRESHOLD = 0.0
ROOM_ROUNDS = 40


@dataclass
class AttentionField:
    """What the agent notices — not everything."""

    capacity: int = 3
    focus: list[str] = field(default_factory=list)

    def notice(self, agent_id: str) -> bool:
        if agent_id in self.focus:
            return True
        if len(self.focus) < self.capacity:
            self.focus.append(agent_id)
            return True
        return False


@dataclass
class AgentPresence:
    """The presence engine's agent: attention/interpretation/motivation/
    emotion/pressure/inhibition/memory."""

    id: str
    persona: dict[str, Any] = field(default_factory=dict)
    emotion: CircumplexState = field(default_factory=CircumplexState)
    attention: AttentionField = field(default_factory=AttentionField)
    motivation: float = 0.5
    pressure: float = 0.0
    inhibition: float = 0.0
    silence_threshold: float = DEFAULT_SILENCE_THRESHOLD
    memory: Any = None  # MemoryStore slice for this agent
    policy: Any = None  # PresencePolicy (tiny/frontier + pruning)
    cost_meter: Any = None

    def urgency(self) -> float:
        """Initiative engine: drive minus restraint.

        pressure and motivation push UP; inhibition pushes DOWN. When the
        balance is negative the agent's move is silence.
        """
        emotional = abs(self.emotion.v) * 0.3 + max(0.0, self.emotion.a) * 0.2
        drive = self.motivation + 0.6 * self.pressure + emotional
        net = drive - self.inhibition
        return float(np.clip(net, -2.0, 2.0))

    @property
    def wants_silence(self) -> bool:
        return self.urgency() <= self.silence_threshold


@dataclass
class _Move:
    urgency: float
    seq: int
    agent: AgentPresence
    gen: int = 0

    def __lt__(self, other: "_Move") -> bool:
        # min-heap: higher urgency pops first
        return self.urgency > other.urgency


class PresenceRoom:
    """A room of presence agents. No round-robin: the heap decides."""

    def __init__(
        self,
        agents: list[AgentPresence],
        social_log: SocialLog,
        run_id: str = "room",
        seed: int = 0,
        rounds: int = ROOM_ROUNDS,
        checkin_probability: float = 0.12,
        initiator_fn: Callable[[AgentPresence, np.random.Generator], dict] | None = None,
    ):
        self.agents = agents
        self.log = social_log
        self.run_id = run_id
        self.seed = seed
        self.rounds = rounds
        self.checkin_probability = checkin_probability
        self.rng = RNGRegistry(seed).generator("room")
        self.initiator_fn = initiator_fn or self._default_initiate
        self.t = 0

    # -- actions ------------------------------------------------------------
    def _default_initiate(self, agent: AgentPresence, rng: np.random.Generator) -> dict:
        """Emergent content: the agent interprets its attention + emotion."""
        topic = rng.choice(["prices", "supply", "hiring", "policy"])
        valence = float(np.clip(agent.emotion.v, -1, 1))
        return {
            "content": f"on {topic} i feel {valence:+.2f}",
            "target": rng.choice([a.id for a in self.agents if a.id != agent.id]) if len(self.agents) > 1 else None,
            "valence": valence,
            "intensity": float(agent.emotion.a),
        }

    def _act(self, agent: AgentPresence) -> list[dict]:
        """One mover's behavior. Silence IS an action when inhibited."""
        if agent.policy is not None and agent.policy.prune(agent):
            return []  # pruned mover: stays quiet, no event, no cost
        if agent.wants_silence:
            return [
                {
                    "kind": "silence",
                    "payload": {
                        "agent": agent.id,
                        "cause": "inhibition",
                        "pressure": agent.pressure,
                        "inhibition": agent.inhibition,
                        "urgency": agent.urgency(),
                        "t": self.t,
                    },
                }
            ]
        if agent.policy is not None:
            agent.policy.record_move(agent)  # cost ledger + model selection hook
        intent = self.initiator_fn(agent, self.rng)
        kind = "reply" if intent.get("target") else "post"
        return [
            {
                "kind": kind,
                "payload": {
                    "agent": agent.id,
                    "target": intent.get("target"),
                    "content": intent["content"],
                    "valence": intent.get("valence", 0.0),
                    "intensity": intent.get("intensity", 0.0),
                    "urgency": agent.urgency(),
                    "t": self.t,
                },
            }
        ]

    # -- event bus ----------------------------------------------------------
    def _apply_event(self, agent: AgentPresence, ev: dict) -> None:
        """Appraisal pass: every agent updates affect/memory from the event."""
        payload = ev["payload"]
        for other in self.agents:
            if other.id == payload["agent"]:
                continue
            if not other.attention.notice(payload["agent"]):
                continue
            valence = payload.get("valence", 0.0)
            intensity = payload.get("intensity", 0.0)
            other.emotion.tune(target_v=valence, target_a=intensity, rate=0.25, decay=0.02)
            if other.memory is not None:
                other.memory.observe(other.id, ev)

    # -- the run ------------------------------------------------------------
    def run(self) -> int:
        """Drives the room until `rounds` events are produced. Returns count.

        Urgency is not static: unpopped agents accumulate `idle_pressure`
        (the room's expectation to hear from them), the room may direct
        attention at a random agent every `attention_every` rounds, and with
        `checkin_probability` the room attends to its QUIETEST member — that
        is when an inhibited agent's pressure surfaces as a `silence` event.
        """
        self.t = 0
        heap: list[_Move] = []
        seq = 0
        self.visitation: list[str] = []
        generation: dict[str, int] = {a.id: 0 for a in self.agents}
        for agent in self.agents:
            seq += 1
            heapq.heappush(heap, _Move(agent.urgency(), seq, agent))
        produced = 0
        idle_pressure = float(self.rng.uniform(0.02, 0.06))
        attention_every = max(3, int(self.rng.integers(3, 6)))
        while produced < self.rounds and heap:
            if (
                self.checkin_probability > 0
                and self.rng.random() < self.checkin_probability
            ):
                candidate = min(
                    (a for a in self.agents if generation[a.id] == 0 or True),
                    key=lambda a: a.urgency(),
                )
                seq += 1
                move = _Move(candidate.urgency(), seq, candidate)
            else:
                move = heapq.heappop(heap)
                while heap and generation[move.agent.id] != move.gen:
                    move = heapq.heappop(heap)
            agent = move.agent
            generation[agent.id] += 1
            self.visitation.append(agent.id)
            events = self._act(agent)
            for ev in events:
                self.log.write(
                    run_id=self.run_id,
                    kind=ev["kind"],
                    payload=ev["payload"],
                    t=ev["payload"].get("t", self.t),
                )
                self._apply_event(agent, ev)
                produced += 1
                self.t = ev["payload"].get("t", self.t)
            # social expectation: the unpopped are being waited on
            for other in self.agents:
                if other.id != agent.id:
                    other.pressure = float(np.clip(other.pressure + idle_pressure, 0.0, 3.0))
            if produced % attention_every == 0:
                target = self.rng.choice([a for a in self.agents if a.id != agent.id] or self.agents)
                target.pressure = float(np.clip(target.pressure + 0.5, 0.0, 3.0))
            # re-insert the mover with fresh drive (small random walk)
            agent.motivation = float(np.clip(agent.motivation + self.rng.normal(0, 0.05), 0.1, 1.0))
            seq += 1
            heapq.heappush(heap, _Move(agent.urgency(), seq, agent, generation[agent.id]))
        return produced