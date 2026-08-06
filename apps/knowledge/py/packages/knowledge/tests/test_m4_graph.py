"""M4 — graph assembly, vector store, subgraph boundedness."""

import numpy as np
from fastapi.testclient import TestClient

from substrate_knowledge.core.storage import InMemoryStore
from substrate_knowledge.core.text import hash_embed
from substrate_knowledge.m2_extraction.extractor import ExtractedEntity, ExtractedRelation
from substrate_knowledge.m3_resolution.canonical_store import CanonicalizationStore
from substrate_knowledge.m4_graph.assembler import GraphAssembler
from substrate_knowledge.m4_graph.graph_store import InMemoryGraph
from substrate_knowledge.m4_graph.subgraph_api import SubgraphExtractor, build_subgraph_app
from substrate_knowledge.m4_graph.vector_store import InMemoryVectorStore, VectorPoint


def _entities(doc_id: str):
    return [
        ExtractedEntity(id="e0", name="Bergmann Components", type="Organization", doc_id=doc_id, chunk_id="0"),
        ExtractedEntity(id="e1", name="Bearings", type="Product", doc_id=doc_id, chunk_id="0"),
        ExtractedEntity(id="e2", name="Acme Corporation", type="Organization", doc_id=doc_id, chunk_id="0"),
    ]


def _relations(doc_id: str):
    return [
        ExtractedRelation(id="r0", source_id="e0", target_id="e1", type="provides", doc_id=doc_id, chunk_id="0"),
        ExtractedRelation(id="r1", source_id="e2", target_id="e1", type="uses", doc_id=doc_id, chunk_id="0"),
    ]


def test_graph_store_upsert_and_temporal_invalidation():
    graph = InMemoryGraph()
    graph.upsert_node("n1", "Organization", "Acme")
    edge, invalidated = graph.upsert_edge("provides", "n1", "n2", source_doc="d1", valid_from="2026-01-01")
    assert invalidated == []
    edge2, invalidated = graph.upsert_edge("provides", "n1", "n2", source_doc="d2", valid_from="2026-02-01")
    assert len(invalidated) == 1
    active = graph.edges()
    assert len(active) == 1
    assert active[0].source_doc == "d2"
    assert graph.edge_count() == 1


def test_vector_store_cosine_ranking_and_filter():
    store = InMemoryVectorStore(dim=128)
    store.upsert(
        [
            VectorPoint(id="a", vector=hash_embed("acme logistics"), payload={"doc_id": "d1", "kind": "chunk"}),
            VectorPoint(id="b", vector=hash_embed("northwind freight"), payload={"doc_id": "d2", "kind": "chunk"}),
            VectorPoint(id="c", vector=hash_embed("acme logistics"), payload={"doc_id": "d3", "kind": "chunk"}),
        ]
    )
    hits = store.search(hash_embed("acme logistics"), k=2)
    assert [h.id for h in hits] == ["a", "c"]
    filtered = store.search(hash_embed("acme logistics"), k=10, payload_filter={"doc_id": "d3"})
    assert [h.id for h in filtered] == ["c"]


def test_assembler_upserts_with_provenance_and_canonical_ids():
    graph = InMemoryGraph()
    canon = CanonicalizationStore(InMemoryStore())
    assembler = GraphAssembler(graph=graph, canonical_store=canon)
    result = assembler.upsert_facts(entities=_entities("d1"), relations=_relations("d1"), source="d1")
    assert result.n_entities == 3
    assert result.n_relations == 2
    assert graph.node_count() == 3
    assert graph.edge_count() == 2
    edges = graph.edges()
    assert all(e.source_doc == "d1" for e in edges)
    assert all(e.valid_from is None for e in edges)
    node = graph.node(result.canonical_by_entity["e0"])
    assert node is not None
    assert node.name == "Bergmann Components"


def test_assembler_invalidates_previous_fact_version():
    graph = InMemoryGraph()
    canon = CanonicalizationStore(InMemoryStore())
    assembler = GraphAssembler(graph=graph, canonical_store=canon)
    assembler.upsert_facts(entities=_entities("d1"), relations=_relations("d1"), source="d1", valid_from="2026-01-01")
    second = assembler.upsert_facts(entities=_entities("d2"), relations=_relations("d2"), source="d2", valid_from="2026-02-01")
    assert second.n_invalidated >= 2
    assert graph.edge_count() == 2


def test_subgraph_extractor_bounds_two_hop_expansion():
    graph = InMemoryGraph()
    for name in ["Acme", "Northwind", "Nordwind", "Vega", "Helios"]:
        graph.upsert_node(f"n{name}", "Organization", name)
    for a, b in (("Acme", "Northwind"), ("Northwind", "Nordwind"), ("Nordwind", "Vega"), ("Vega", "Helios")):
        graph.upsert_edge("provides", f"n{a}", f"n{b}", source_doc=f"doc-{a}-{b}")
    vectors = InMemoryVectorStore()
    vectors.upsert(
        [
            VectorPoint(id=f"node:n{name}", vector=hash_embed(name), payload={"kind": "node", "node_id": f"n{name}"})
            for name in ["Acme", "Northwind", "Nordwind", "Vega", "Helios"]
        ]
    )
    extractor = SubgraphExtractor(graph, vectors, max_hops=2, max_nodes=3)
    result = extractor.extract("Which company is Northwind's supplier?")
    assert len(result.entities) <= 3
    assert result.bounded is True
    assert result.capped is True
    assert any(e.id == "nNorthwind" for e in result.entities)
    assert result.evidence_docs


def test_subgraph_extractor_two_hop_chain_shape():
    graph = InMemoryGraph()
    for name in ["Acme", "Northwind", "Nordwind"]:
        graph.upsert_node(f"n{name}", "Organization", name)
    for a, b in (("Acme", "Northwind"), ("Northwind", "Nordwind")):
        graph.upsert_edge("provides", f"n{a}", f"n{b}", source_doc=f"doc-{a}-{b}")
    extractor = SubgraphExtractor(graph, max_hops=2, max_nodes=10)
    result = extractor.extract("Acme")
    names = {e.name for e in result.entities}
    assert names == {"Acme", "Northwind", "Nordwind"}


def test_subgraph_extractor_caps_wide_neighborhood():
    graph = InMemoryGraph()
    graph.upsert_node("hub", "Organization", "Hub")
    for i in range(20):
        graph.upsert_node(f"w{i}", "Organization", f"W{i}")
        graph.upsert_edge("provides", "hub", f"w{i}", source_doc=f"doc-{i}")
    extractor = SubgraphExtractor(graph, max_hops=2, max_nodes=5)
    result = extractor.extract("Hub")
    assert len(result.entities) <= 5
    assert result.capped is True


def test_subgraph_api_http():
    graph = InMemoryGraph()
    graph.upsert_node("nAcme", "Organization", "Acme")
    graph.upsert_node("nNorthwind", "Organization", "Northwind")
    graph.upsert_edge("provides", "nAcme", "nNorthwind", source_doc="d1")
    extractor = SubgraphExtractor(graph, max_hops=2, max_nodes=5)
    client = TestClient(build_subgraph_app(extractor))
    response = client.post("/subgraph", json={"query": "Acme"})
    assert response.status_code == 200
    body = response.json()
    assert body["bounded"] is True
    assert len(body["entities"]) == 2
    assert body["evidence_docs"] == ["d1"]
