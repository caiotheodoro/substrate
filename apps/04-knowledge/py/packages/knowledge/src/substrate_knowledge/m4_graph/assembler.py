"""A-K-16 graph-assembler.

Upserts resolved facts with provenance and Graphiti-style validity windows:
entities become nodes (canonical ids via the canonicalization store),
relations become edges; re-assembling a fact with a newer validity window
invalidates the previous version of that edge (valid_to set) — so the graph
is versioned, not overwritten.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from substrate_knowledge.m2_extraction.extractor import ExtractedEntity, ExtractedRelation
from substrate_knowledge.m3_resolution.blocker import EntityRecord
from substrate_knowledge.m3_resolution.canonical_store import CanonicalizationStore
from substrate_knowledge.m4_graph.graph_store import InMemoryGraph


@dataclass
class AssemblyResult:
    n_entities: int
    n_relations: int
    n_invalidated: int = 0
    canonical_by_entity: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "n_entities": self.n_entities,
            "n_relations": self.n_relations,
            "n_invalidated": self.n_invalidated,
            "canonical_by_entity": self.canonical_by_entity,
        }


class GraphAssembler:
    def __init__(self, graph: InMemoryGraph, canonical_store: CanonicalizationStore) -> None:
        self.graph = graph
        self.canonical_store = canonical_store

    def upsert_facts(
        self,
        *,
        entities: list[ExtractedEntity],
        relations: list[ExtractedRelation],
        source: str,
        chunk_id: str | None = None,
        valid_from: str | None = None,
        valid_to: str | None = None,
    ) -> AssemblyResult:
        """Resolve entity names to canonical ids, upsert nodes + edges with
        provenance and validity windows."""
        canonical_by_entity: dict[str, str] = {}
        node_by_canonical: dict[str, str] = {}
        for entity in entities:
            record = EntityRecord(
                entity_id=entity.id,
                name=entity.name,
                type=entity.type,
                source=source,
            )
            canonical_id = self.canonical_store.resolve_alias(entity.name)
            if canonical_id is None:
                canonical_id = self.canonical_store.create_canonical(record)
            else:
                self.canonical_store.merge(canonical_id, entity.name, record, audited_by="assembler")
            canonical_by_entity[entity.id] = canonical_id
            if canonical_id not in node_by_canonical:
                node_by_canonical[canonical_id] = self.graph.upsert_node(
                    node_id=canonical_id,
                    node_type=entity.type,
                    name=entity.name,
                    properties=dict(entity.properties),
                    source=source,
                    valid_from=valid_from,
                    valid_to=valid_to,
                ).id

        invalidated: list[str] = []
        for relation in relations:
            src_canonical = canonical_by_entity.get(relation.source_id)
            tgt_canonical = canonical_by_entity.get(relation.target_id)
            if src_canonical is None or tgt_canonical is None:
                continue
            _, inval = self.graph.upsert_edge(
                edge_type=relation.type,
                source_id=src_canonical,
                target_id=tgt_canonical,
                properties={
                    **dict(relation.properties),
                    "chunk_id": chunk_id,
                    "source_doc": source,
                },
                source_doc=source,
                valid_from=valid_from,
                valid_to=valid_to,
            )
            invalidated.extend(inval)

        return AssemblyResult(
            n_entities=len(entities),
            n_relations=len(relations),
            n_invalidated=len(invalidated),
            canonical_by_entity=canonical_by_entity,
        )
