"""A-K-19 subgraph-extractor — svc :8203.

Query -> candidate entities (vector search over node embeddings, name-match
fallback) -> bounded 2-hop evidence subgraph. Bounding is implemented here
and tested: `max_nodes` caps BFS expansion, `max_edges` caps collected
evidence edges, and the result always reports whether the budget was hit
(`capped`). Evidence docs are the provenance of the subgraph's edges.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from substrate_knowledge.core.text import hash_embed
from substrate_knowledge.m4_graph.graph_store import GraphEdge, GraphNode, InMemoryGraph
from substrate_knowledge.m4_graph.vector_store import InMemoryVectorStore, VectorPoint


@dataclass
class SubgraphResult:
    query: str
    entities: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    evidence_docs: list[str] = field(default_factory=list)
    bounded: bool = True
    capped: bool = False
    stats: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "entities": [n.to_dict() for n in self.entities],
            "edges": [e.to_dict() for e in self.edges],
            "evidence_docs": self.evidence_docs,
            "bounded": self.bounded,
            "capped": self.capped,
            "stats": self.stats,
        }


class SubgraphExtractor:
    def __init__(
        self,
        graph: InMemoryGraph,
        vectors: InMemoryVectorStore | None = None,
        max_hops: int = 2,
        max_nodes: int = 32,
        max_edges: int = 64,
    ) -> None:
        self.graph = graph
        self.vectors = vectors
        self.max_hops = max_hops
        self.max_nodes = max_nodes
        self.max_edges = max_edges

    # ------------------------------------------------------------------
    def extract(self, query: str, *, k_candidates: int = 5) -> SubgraphResult:
        # The node budget covers seed candidates + expansion, so the result
        # can never exceed max_nodes regardless of candidate quality.
        seeds = self._candidates(query, min(k_candidates, self.max_nodes))
        capped = len(seeds) == min(k_candidates, self.max_nodes)
        expanded: set[str] = set()
        capped |= self._expand(seeds, expanded)

        entities = []
        for node_id in sorted(expanded):
            node = self.graph.node(node_id)
            if node is not None:
                entities.append(node)
        if not entities:
            return SubgraphResult(
                query=query,
                bounded=True,
                capped=capped,
                stats={"candidates": seeds, "expanded": sorted(expanded)},
            )

        edge_ids: list[str] = []
        edge_limit = min(self.max_edges, len(self.graph.edges()))
        for edge in self.graph.edges():
            if edge.source in expanded and edge.target in expanded:
                edge_ids.append(edge.id)
                if len(edge_ids) >= edge_limit:
                    break
        edges = [e for e in self.graph.edges() if e.id in edge_ids]

        evidence_docs = sorted({e.source_doc for e in edges if e.source_doc})
        return SubgraphResult(
            query=query,
            entities=entities,
            edges=edges,
            evidence_docs=evidence_docs,
            bounded=True,
            capped=capped or len(edge_ids) >= self.max_edges,
            stats={"candidates": seeds, "expanded": sorted(expanded), "n_edges": len(edge_ids)},
        )

    # ------------------------------------------------------------------
    def _candidates(self, query: str, k: int) -> list[str]:
        if self.vectors is not None and self.vectors.count() > 0:
            query_vec = hash_embed(query)
            hits = self.vectors.search(query_vec, k=k, payload_filter={"kind": "node"})
            if hits:
                return [h.payload.get("node_id", h.id) for h in hits]
        return self._name_match(query, k)

    def _name_match(self, query: str, k: int) -> list[str]:
        """Deterministic fallback: nodes whose name tokens appear in the query."""
        query_terms = set(query.lower().split())
        scored = []
        for node in self.graph.nodes():
            name_terms = set(node.name.lower().split())
            overlap = len(query_terms & name_terms)
            if overlap:
                scored.append((overlap, node.name, node.id))
        scored.sort(key=lambda t: (-t[0], t[1]))
        return [node_id for _, _, node_id in scored[:k]]

    def _expand(self, seeds: list[str], expanded: set[str]) -> bool:
        """2-hop BFS expansion with a node budget; returns whether the
        budget was hit (expansion was truncated)."""
        capped = False
        frontier = [s for s in seeds if self.graph.node(s) is not None]
        expanded.update(frontier)
        for _ in range(self.max_hops):
            if not frontier:
                break
            nxt: set[str] = set()
            for node_id in frontier:
                for edge in self.graph.edges():
                    if edge.source == node_id and edge.target not in expanded and edge.target not in nxt:
                        nxt.add(edge.target)
                    if edge.target == node_id and edge.source not in expanded and edge.source not in nxt:
                        nxt.add(edge.source)
            if len(expanded) + len(nxt) > self.max_nodes:
                remaining = self.max_nodes - len(expanded)
                nxt = set(sorted(nxt)[: max(0, remaining)])
                capped = True
            expanded.update(nxt)
            frontier = list(nxt)
        return capped


def build_subgraph_app(extractor: SubgraphExtractor) -> Any:
    """svc :8203 — POST /subgraph {query} -> bounded evidence subgraph."""
    from fastapi import Body, FastAPI

    app = FastAPI(title="subgraph-extractor", version="0.1.0")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "service": "subgraph", "port": 8203}

    @app.post("/subgraph")
    def subgraph(query: str = Body(..., embed=True)) -> dict:
        return extractor.extract(query).to_dict()

    return app
