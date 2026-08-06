"""A-K-20 ontology registry — the single Pydantic source of truth.

Entity types, edge types and constraints live HERE and nowhere else. The
extractor (M2), resolver (M3) and assembler (M4) all import from this module;
the registry is the only place a new entity/edge type may be declared.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PropertyDef(BaseModel):
    name: str
    value_type: str = "string"  # string | number | date | boolean
    description: str = ""
    required: bool = False


class EntityType(BaseModel):
    name: str
    description: str = ""
    properties: dict[str, PropertyDef] = Field(default_factory=dict)


class EdgeType(BaseModel):
    name: str
    description: str = ""
    source: str  # entity type name
    target: str  # entity type name
    properties: dict[str, PropertyDef] = Field(default_factory=dict)
    allows_multiple: bool = True


class OntologyRegistry(BaseModel):
    """The type-constrained schema. Pydantic == schema + validation."""

    name: str = "default"
    entities: dict[str, EntityType] = Field(default_factory=dict)
    edges: dict[str, EdgeType] = Field(default_factory=dict)

    # ------------------------------------------------------------------
    # lookup
    # ------------------------------------------------------------------
    def entity_type(self, name: str) -> EntityType | None:
        return self.entities.get(name)

    def edge_type(self, name: str) -> EdgeType | None:
        return self.edges.get(name)

    def entity_names(self) -> list[str]:
        return sorted(self.entities)

    def edge_names(self) -> list[str]:
        return sorted(self.edges)

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump()

    # ------------------------------------------------------------------
    # validation helpers (violations, never exceptions)
    # ------------------------------------------------------------------
    def validate_entity(self, entity_type: str, properties: dict[str, Any] | None = None) -> list[str]:
        et = self.entity_type(entity_type)
        violations: list[str] = []
        if et is None:
            return [f"unknown_entity_type:{entity_type}"]
        props = properties or {}
        declared = set(et.properties)
        for key in props:
            if key not in declared:
                violations.append(f"undeclared_property:{entity_type}.{key}")
        for name, prop in et.properties.items():
            if prop.required and name not in props:
                violations.append(f"missing_required_property:{entity_type}.{name}")
        return violations

    def validate_relation(
        self,
        edge_type: str,
        source_type: str,
        target_type: str,
        properties: dict[str, Any] | None = None,
    ) -> list[str]:
        et = self.edge_type(edge_type)
        if et is None:
            return [f"unknown_edge_type:{edge_type}"]
        violations: list[str] = []
        if et.source != source_type:
            violations.append(f"edge_endpoint_mismatch:{edge_type}.source expects {et.source}, got {source_type}")
        if et.target != target_type:
            violations.append(f"edge_endpoint_mismatch:{edge_type}.target expects {et.target}, got {target_type}")
        props = properties or {}
        declared = set(et.properties)
        for key in props:
            if key not in declared:
                violations.append(f"undeclared_property:{edge_type}.{key}")
        return violations


# ---------------------------------------------------------------------------
# Default ontology — the shipped type system. Extend via the registry, never
# by forking. Graphiti-style temporal facts attach validity windows at
# assembly time, not here.
# ---------------------------------------------------------------------------

DEFAULT_ONTOLOGY = OntologyRegistry(
    name="substrate-default",
    entities={
        "Organization": EntityType(
            name="Organization",
            description="Company, agency, institution, or organized group.",
            properties={
                "industry": PropertyDef(name="industry", value_type="string"),
                "founded": PropertyDef(name="founded", value_type="date"),
                "headquarters": PropertyDef(name="headquarters", value_type="string"),
            },
        ),
        "Person": EntityType(
            name="Person",
            description="An individual with a role in the corpus.",
            properties={
                "role": PropertyDef(name="role", value_type="string"),
            },
        ),
        "Product": EntityType(
            name="Product",
            description="A product, service, or offering.",
            properties={
                "version": PropertyDef(name="version", value_type="string"),
                "price": PropertyDef(name="price", value_type="number"),
            },
        ),
        "Technology": EntityType(
            name="Technology",
            description="A technology, framework, or protocol.",
        ),
        "Document": EntityType(
            name="Document",
            description="A report, article, or publication referenced by the corpus.",
            properties={
                "author": PropertyDef(name="author", value_type="string"),
                "published": PropertyDef(name="published", value_type="date"),
            },
        ),
        "Topic": EntityType(
            name="Topic",
            description="A subject, market, or domain area.",
        ),
        "Location": EntityType(
            name="Location",
            description="A city, region, or country.",
        ),
        "Event": EntityType(
            name="Event",
            description="A dated occurrence.",
            properties={"date": PropertyDef(name="date", value_type="date", required=True)},
        ),
        "Metric": EntityType(
            name="Metric",
            description="A quantitative measure.",
            properties={"value": PropertyDef(name="value", value_type="number", required=True)},
        ),
    },
    edges={
        "employs": EdgeType(name="employs", source="Organization", target="Person"),
        "developed_by": EdgeType(name="developed_by", source="Product", target="Organization"),
        "provides": EdgeType(name="provides", source="Organization", target="Product"),
        "uses": EdgeType(name="uses", source="Organization", target="Technology"),
        "located_in": EdgeType(name="located_in", source="Organization", target="Location"),
        "acquired_by": EdgeType(name="acquired_by", source="Organization", target="Organization"),
        "founded_by": EdgeType(name="founded_by", source="Organization", target="Person"),
        "mentions": EdgeType(name="mentions", source="Document", target="Topic"),
        "authored_by": EdgeType(name="authored_by", source="Document", target="Person"),
        "published_by": EdgeType(name="published_by", source="Document", target="Organization"),
        "part_of": EdgeType(name="part_of", source="Product", target="Product"),
        "conflicts_with": EdgeType(name="conflicts_with", source="Topic", target="Topic"),
        "related_to": EdgeType(name="related_to", source="Topic", target="Topic"),
        "measured_by": EdgeType(name="measured_by", source="Metric", target="Topic"),
        "occurred_at": EdgeType(name="occurred_at", source="Event", target="Location"),
    },
)
