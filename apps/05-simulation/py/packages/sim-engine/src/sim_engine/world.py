"""A-S-16 sim-world: SKUs/sectors/macro variables + clock + event bus."""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Any, Callable


class SimulationClock:
    """Discrete, monotonically increasing sim clock."""

    def __init__(self) -> None:
        self.t = 0

    def tick(self, n: int = 1) -> int:
        self.t += n
        return self.t

    @property
    def now(self) -> int:
        return self.t


@dataclass
class Event:
    kind: str
    payload: dict[str, Any]
    seq: int = 0


class EventBus:
    """Publish/subscribe event bus in the same append-only spirit as C1."""

    def __init__(self) -> None:
        self._seq = 0
        self._handlers: list[Callable[[Event], None]] = []
        self.history: list[Event] = []

    def publish(self, kind: str, payload: dict[str, Any]) -> Event:
        self._seq += 1
        ev = Event(kind=kind, payload=payload, seq=self._seq)
        self.history.append(ev)
        for handler in self._handlers:
            handler(ev)
        return ev

    def subscribe(self, handler: Callable[[Event], None]) -> None:
        self._handlers.append(handler)

    def drain(self) -> list[Event]:
        out = self.history
        self.history = []
        return out


@dataclass
class Sector:
    """A world sub-system (SKU line, sector): demand/supply with shock memory."""

    name: str
    demand: float = 1.0
    supply: float = 1.0
    price: float = 1.0
    shock_exposure: float = 0.0  # 0..1 how much a shock moves this sector

    def apply_shock(self, magnitude: float, channel: str) -> None:
        effect = magnitude * self.shock_exposure
        if channel == "demand":
            self.demand = max(0.1, self.demand * (1 + effect))
        elif channel == "supply":
            self.supply = max(0.1, self.supply * (1 - effect))
        else:
            self.price = max(0.1, self.price * (1 + effect))


class World:
    """Macro variables + sectors + clock + event bus (A-S-16)."""

    def __init__(self, name: str = "world") -> None:
        self.name = name
        self.clock = SimulationClock()
        self.events = EventBus()
        self.macro: dict[str, float] = {}
        self.sectors: dict[str, Sector] = {}

    def add_macro(self, key: str, value: float) -> "World":
        self.macro[key] = float(value)
        return self

    def add_sector(self, sector: Sector) -> "World":
        self.sectors[sector.name] = sector
        return self

    def snapshot(self) -> dict[str, Any]:
        return {
            "t": self.clock.now,
            "macro": dict(self.macro),
            "sectors": {k: {"demand": s.demand, "supply": s.supply, "price": s.price} for k, s in self.sectors.items()},
        }