"""A-K-28 graph-health-monitor.

Entity coverage per source, relation density, orphan-cluster drift,
connectivity. All pure functions over the graph store, so the monitor is a
deterministic report an operator can diff run over run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from substrate_knowledge.m4_graph.graph_store import InMemoryGraph


@dataclass
class HealthReport:
    n_nodes: int
    n_edges: int
    n_sources: int
    entity_coverage: dict[str, int]
    relation_density: float
    giant_component_fraction: float
    n_components: int
    n_orphans: int
    orphan_fraction: float
    connectivity: float

    def to_dict(self) -> dict:
        return {
            "n_nodes": self.n_nodes,
            "n_edges": self.n_edges,
            "n_sources": self.n_sources,
            "entity_coverage": self.entity_coverage,
            "relation_density": round(self.relation_density, 4),
            "giant_component_fraction": round(self.giant_component_fraction, 4),
            "n_components": self.n_components,
            "n_orphans": self.n_orphans,
            "orphan_fraction": round(self.orphan_fraction, 4),
            "connectivity": round(self.connectivity, 4),
        }


class GraphHealthMonitor:
    def report(self, graph: InMemoryGraph, provenance: list[tuple[str, str]] | None = None) -> HealthReport:
        """`provenance`: (node_id, source) pairs; defaults to node.source."""
        nodes = graph.nodes()
        edges = graph.edges()
        if provenance is None:
            provenance = [(n.id, n.source or "unknown") for n in nodes]

        coverage: dict[str, int] = {}
        for node_id, source in provenance:
            coverage[source] = coverage.get(source, 0) + 1

        n_edges = len(edges)
        n_nodes = len(nodes)
        density = n_edges / n_nodes if n_nodes else 0.0

        components = self._components(nodes, edges)
        giant = max(components) if components else 0
        n_components = len([c for c in components if c > 1])
        orphans = sum(1 for c in components if c == 1)
        giant_fraction = giant / n_nodes if n_nodes else 0.0
        connectivity = (n_components + orphans) / n_nodes if n_nodes else 0.0

        return HealthReport(
            n_nodes=n_nodes,
            n_edges=n_edges,
            n_sources=len(coverage),
            entity_coverage=coverage,
            relation_density=density,
            giant_component_fraction=giant_fraction,
            n_components=n_components,
            n_orphans=orphans,
            orphan_fraction=orphans / n_nodes if n_nodes else 0.0,
            connectivity=connectivity,
        )

    @staticmethod
    def _components(nodes: list[Any], edges: list[Any]) -> list[int]:
        if not nodes:
            return []
        adjacency: dict[str, set[str]] = {n.id: set() for n in nodes}
        for edge in edges:
            if edge.valid_to is not None:
                continue
            if edge.source in adjacency and edge.target in adjacency:
                adjacency[edge.source].add(edge.target)
                adjacency[edge.target].add(edge.source)
        seen: set[str] = set()
        sizes: list[int] = []
        for node in nodes:
            if node.id in seen:
                continue
            stack = [node.id]
            seen.add(node.id)
            size = 0
            while stack:
                current = stack.pop()
                size += 1
                for nb in adjacency.get(current, ()):
                    if nb not in seen:
                        seen.add(nb)
                        stack.append(nb)
            sizes.append(size)
        return sizes
