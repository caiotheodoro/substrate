"""A-K-10 golden-slices-dataset — small labeled slices, in git.

Slices are engineered so the deterministic PatternExtractor produces
verifiable extractions (the real-docs + LLM-assisted expansion is a v2
exercise per BUILD.md). Each slice carries gold entities and gold relations
in ontology terms.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GoldEntity:
    name: str
    type: str


@dataclass(frozen=True)
class GoldRelation:
    source: str
    target: str
    type: str


@dataclass
class GoldSlice:
    slice_id: str
    text: str
    entities: list[GoldEntity] = field(default_factory=list)
    relations: list[GoldRelation] = field(default_factory=list)
    source_doc: str = "golden"


GOLDEN_SLICES: list[GoldSlice] = [
    GoldSlice(
        slice_id="slice-supply-chain",
        text=(
            "Bergmann Components supplies Bearings to Acme Corporation. "
            "Northwind Logistics provides Freight Services to Halcyon Electronics. "
            "Vega Assemblies manufactures Chassis Frames for Acme Corporation."
        ),
        entities=[
            GoldEntity("Bergmann Components", "Organization"),
            GoldEntity("Bearings", "Product"),
            GoldEntity("Acme Corporation", "Organization"),
            GoldEntity("Northwind Logistics", "Organization"),
            GoldEntity("Freight Services", "Product"),
            GoldEntity("Halcyon Electronics", "Organization"),
            GoldEntity("Vega Assemblies", "Organization"),
            GoldEntity("Chassis Frames", "Product"),
        ],
        relations=[
            GoldRelation("Bergmann Components", "Bearings", "provides"),
            GoldRelation("Northwind Logistics", "Freight Services", "provides"),
            GoldRelation("Vega Assemblies", "Chassis Frames", "provides"),
        ],
    ),
    GoldSlice(
        slice_id="slice-properties",
        text=(
            "Acme Corporation is located in Berlin. "
            "Northwind Logistics employs Laura Berg. "
            "Acme Corporation uses SensorGrid Technology for tracking."
        ),
        entities=[
            GoldEntity("Acme Corporation", "Organization"),
            GoldEntity("Berlin", "Location"),
            GoldEntity("Northwind Logistics", "Organization"),
            GoldEntity("Laura Berg", "Person"),
            GoldEntity("SensorGrid Technology", "Technology"),
        ],
        relations=[
            GoldRelation("Acme Corporation", "Berlin", "located_in"),
            GoldRelation("Northwind Logistics", "Laura Berg", "employs"),
            GoldRelation("Acme Corporation", "SensorGrid Technology", "uses"),
        ],
    ),
    GoldSlice(
        slice_id="slice-acquisition",
        text=(
            "Fusion Power GmbH acquired Helio Energy in March. "
            "Helio Energy develops SensorGrid Technology."
        ),
        entities=[
            GoldEntity("Fusion Power GmbH", "Organization"),
            GoldEntity("Helio Energy", "Organization"),
            GoldEntity("SensorGrid Technology", "Technology"),
        ],
        relations=[
            GoldRelation("Helio Energy", "Fusion Power GmbH", "acquired_by"),
            GoldRelation("SensorGrid Technology", "Helio Energy", "developed_by"),
        ],
    ),
]
