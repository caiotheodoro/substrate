"""A-S-28 memory-store: episodic memory, social graph, alliance state.

Interface-first: InMemoryMemoryStore is the default (used in tests); the
DuckDB variant persists episodes/edges/alliances behind the same ABC.
Alliance state is tracked explicitly — it is what the believability probes
measure (reciprocity → alliance edges).
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MemoryEntry:
    agent_id: str
    kind: str  # episode | observation
    content: dict[str, Any]
    t: int = 0


@dataclass
class AllianceState:
    """Weighted alliance between two agents (reciprocity accumulator)."""

    agent_a: str
    agent_b: str
    weight: float = 0.0
    since_t: int = 0

    @property
    def formed(self) -> bool:
        return self.weight >= 3.0


class MemoryStore(ABC):
    @abstractmethod
    def add(self, entry: MemoryEntry) -> None: ...

    @abstractmethod
    def recall(self, agent_id: str, k: int = 5, kind: str | None = None) -> list[MemoryEntry]: ...

    @abstractmethod
    def observe(self, observer_id: str, event: dict[str, Any]) -> None:
        """Social observation pass: episode + reciprocity + alliance update."""
        ...

    @abstractmethod
    def edge_weight(self, a: str, b: str) -> float: ...

    @abstractmethod
    def alliances(self) -> list[AllianceState]: ...


class InMemoryMemoryStore(MemoryStore):
    def __init__(self) -> None:
        self._mem: dict[str, list[MemoryEntry]] = {}
        self._graph: dict[tuple[str, str], float] = {}
        self._alliances: dict[tuple[str, str], AllianceState] = {}
        self._t = 0

    def add(self, entry: MemoryEntry) -> None:
        self._mem.setdefault(entry.agent_id, []).append(entry)

    def recall(self, agent_id: str, k: int = 5, kind: str | None = None) -> list[MemoryEntry]:
        rows = [e for e in self._mem.get(agent_id, []) if kind is None or e.kind == kind]
        return rows[-k:]

    def observe(self, observer_id: str, event: dict[str, Any]) -> None:
        payload = event["payload"]
        actor = payload.get("agent")
        if actor is None or actor == observer_id:
            return
        self._t += 1
        self.add(
            MemoryEntry(
                agent_id=observer_id,
                kind="observation",
                content={"actor": actor, "kind": event["kind"], "content": payload.get("content")},
                t=self._t,
            )
        )
        self._graph[(observer_id, actor)] = self._graph.get((observer_id, actor), 0.0) + 1.0
        pair = tuple(sorted((observer_id, actor)))
        alliance = self._alliances.get(pair)
        if alliance is None:
            alliance = AllianceState(agent_a=pair[0], agent_b=pair[1], since_t=self._t)
            self._alliances[pair] = alliance
        alliance.weight += 0.5

    def edge_weight(self, a: str, b: str) -> float:
        return self._graph.get((a, b), 0.0)

    def alliances(self) -> list[AllianceState]:
        return list(self._alliances.values())


class DuckDBMemoryStore(InMemoryMemoryStore):
    """DuckDB-persisted variant of the same store."""

    def __init__(self, conn=None, table_prefix: str = "presence"):
        super().__init__()
        self._conn = conn
        self._prefix = table_prefix
        if self._conn is not None:
            self._create_tables()

    def _create_tables(self) -> None:
        p = self._prefix
        self._conn.execute(
            f"CREATE TABLE IF NOT EXISTS {p}_memory (agent VARCHAR, kind VARCHAR, content JSON, t INTEGER)"
        )
        self._conn.execute(
            f"CREATE TABLE IF NOT EXISTS {p}_edges (a VARCHAR, b VARCHAR, weight DOUBLE)"
        )
        self._conn.execute(
            f"CREATE TABLE IF NOT EXISTS {p}_alliance (a VARCHAR, b VARCHAR, weight DOUBLE, since_t INTEGER)"
        )

    def add(self, entry: MemoryEntry) -> None:
        super().add(entry)
        if self._conn is not None:
            self._conn.execute(
                f"INSERT INTO {self._prefix}_memory VALUES (?,?,?,?)",
                [entry.agent_id, entry.kind, json.dumps(entry.content), entry.t],
            )

    def observe(self, observer_id: str, event: dict[str, Any]) -> None:
        before = super().edge_weight(observer_id, event["payload"].get("agent", ""))
        super().observe(observer_id, event)
        if self._conn is not None:
            payload = event["payload"]
            actor = payload.get("agent")
            if actor and actor != observer_id:
                self._conn.execute(
                    f"INSERT OR REPLACE INTO {self._prefix}_edges VALUES (?,?,?)",
                    [observer_id, actor, self.edge_weight(observer_id, actor)],
                )
                pair = tuple(sorted((observer_id, actor)))
                al = self._alliances[pair]
                self._conn.execute(
                    f"INSERT OR REPLACE INTO {self._prefix}_alliance VALUES (?,?,?,?)",
                    [al.agent_a, al.agent_b, al.weight, al.since_t],
                )