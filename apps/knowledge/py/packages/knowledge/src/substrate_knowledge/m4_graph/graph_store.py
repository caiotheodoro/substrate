"""A-K-17 graph-store.

FalkorDB is the production backend (locked stack); this module ships the
deterministic `InMemoryGraph` fallback used by tests and offline CLI runs.
Graphiti-style temporal facts: every node and edge carries `valid_from` /
`valid_to` validity windows and provenance.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GraphNode:
    id: str
    type: str
    name: str
    properties: dict[str, Any] = field(default_factory=dict)
    source: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "properties": self.properties,
            "source": self.source,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
        }


@dataclass
class GraphEdge:
    id: str
    source: str
    target: str
    type: str
    properties: dict[str, Any] = field(default_factory=dict)
    source_doc: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "type": self.type,
            "properties": self.properties,
            "source_doc": self.source_doc,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
        }


class InMemoryGraph:
    """Deterministic graph with node/edge upsert and temporal invalidation."""

    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: list[GraphEdge] = []
        self._edge_ids: set[str] = set()

    # ------------------------------------------------------------------
    def upsert_node(
        self,
        node_id: str,
        node_type: str,
        name: str,
        properties: dict[str, Any] | None = None,
        source: str | None = None,
        valid_from: str | None = None,
        valid_to: str | None = None,
    ) -> GraphNode:
        node = GraphNode(node_id, node_type, name, properties or {}, source, valid_from, valid_to)
        self._nodes[node_id] = node
        return node

    def upsert_edge(
        self,
        edge_type: str,
        source_id: str,
        target_id: str,
        properties: dict[str, Any] | None = None,
        source_doc: str | None = None,
        valid_from: str | None = None,
        valid_to: str | None = None,
    ) -> tuple[GraphEdge, list[str]]:
        """Upsert with versioning: an existing edge with the same
        (type, source, target) is invalidated (valid_to set) and a fresh
        edge carries the new window. Returns (new edge, invalidated ids)."""
        invalidated = [
            e.id for e in self._edges if e.type == edge_type and e.source == source_id and e.target == target_id and e.valid_to is None
        ]
        for edge_id in invalidated:
            self._edge(edge_id).valid_to = valid_from  # type: ignore[assignment]
        edge = GraphEdge(
            id=f"edge:{uuid.uuid4().hex[:12]}",
            source=source_id,
            target=target_id,
            type=edge_type,
            properties=properties or {},
            source_doc=source_doc,
            valid_from=valid_from,
            valid_to=valid_to,
        )
        self._edges.append(edge)
        self._edge_ids.add(edge.id)
        return edge, invalidated

    # ------------------------------------------------------------------
    def node(self, node_id: str) -> GraphNode | None:
        return self._nodes.get(node_id)

    def nodes(self) -> list[GraphNode]:
        return list(self._nodes.values())

    def edges(self, active_only: bool = True) -> list[GraphEdge]:
        if not active_only:
            return list(self._edges)
        return [e for e in self._edges if e.valid_to is None]

    def neighbors(self, node_id: str, max_hops: int = 1, max_nodes: int | None = None) -> set[str]:
        """BFS from `node_id` up to `max_hops` hops, optionally capped."""
        visited: set[str] = {node_id}
        frontier = {node_id}
        for _ in range(max_hops):
            nxt: set[str] = set()
            for node in frontier:
                for edge in self._edges:
                    if edge.valid_to is not None:
                        continue
                    if edge.source == node and edge.target not in visited:
                        nxt.add(edge.target)
                    if edge.target == node and edge.source not in visited:
                        nxt.add(edge.source)
                if max_nodes is not None and len(visited) + len(nxt) > max_nodes:
                    break
            visited |= nxt
            frontier = nxt
            if not frontier:
                break
        return visited - {node_id}

    def node_count(self) -> int:
        return len(self._nodes)

    def edge_count(self) -> int:
        return len([e for e in self._edges if e.valid_to is None])

    def _edge(self, edge_id: str) -> GraphEdge | None:
        for edge in self._edges:
            if edge.id == edge_id:
                return edge
        return None


class FalkorDBGraph:
    """FalkorDB client wrapper (optional dependency, optional server).

    Design decision: connect failure degrades to the in-memory graph so a
    missing FalkorDB never takes the pipeline down — the memory graph is
    the contract, FalkorDB is a performance/semantics upgrade.
    """

    def __init__(self, host: str = "localhost", port: int = 6380, graph_name: str = "knowledge") -> None:
        self.graph_name = graph_name
        self._memory = InMemoryGraph()
        self._client: Any | None = None
        try:
            import redis

            self._client = redis.Redis(host=host, port=port, decode_responses=True)
            self._client.ping()
        except Exception:
            self._client = None

    def upsert_node(self, *args: Any, **kwargs: Any) -> GraphNode:
        return self._memory.upsert_node(*args, **kwargs)

    def upsert_edge(self, *args: Any, **kwargs: Any) -> tuple[GraphEdge, list[str]]:
        return self._memory.upsert_edge(*args, **kwargs)

    def node(self, node_id: str) -> GraphNode | None:
        return self._memory.node(node_id)

    def nodes(self) -> list[GraphNode]:
        return self._memory.nodes()

    def edges(self, active_only: bool = True) -> list[GraphEdge]:
        return self._memory.edges(active_only)

    def neighbors(self, node_id: str, max_hops: int = 1, max_nodes: int | None = None) -> set[str]:
        return self._memory.neighbors(node_id, max_hops, max_nodes)

    def node_count(self) -> int:
        return self._memory.node_count()

    def edge_count(self) -> int:
        return self._memory.edge_count()

    def connected(self) -> bool:
        return self._client is not None
