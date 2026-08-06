"""A-K-06 type-constrained-extractor.

Entities and relations are extracted against the ontology registry
(A-K-20) and every output is validated against it; violations are reported,
never raised. Two implementations behind one protocol:

- `PatternExtractor` — deterministic lexicon/proper-noun stub used by tests,
  golden-slice evals and offline CLI runs. No LLM.
- `InstructorExtractor` — real path: prompt carries the registry schema as
  the type constraint; structured output via the LLM provider's response-
  format negotiation. Instructor itself is optional — when importable it
  wraps the HTTP client for tighter constraint enforcement.
"""

from __future__ import annotations

import re
from typing import Any, Protocol

from pydantic import BaseModel, Field

from substrate_knowledge.core.ontology import DEFAULT_ONTOLOGY, OntologyRegistry

_PROP = re.compile(r"\b([A-Z][A-Za-z'-]+(?:\s+[A-Z][A-Za-z'-]+){0,2})\b")
_SKIP_PROPER = frozenset(
    (
        "The This These Those A An In At On By For With During After Before Its Their However "
        "Meanwhile But And Or Supporters Critics Opponents Regulators Analysts Industry Investors "
        "Auditors Engineers New Top Best Strong Weak January February March April May June July "
        "August September October November December Monday Tuesday Wednesday Thursday Friday "
        "Saturday Sunday"
    ).split()
)

_ENTITY_HINT: dict[str, str] = {
    "logistics": "Organization",
    "components": "Organization",
    "cargo": "Organization",
    "assemblies": "Organization",
    "electronics": "Organization",
    "corporation": "Organization",
    "corp": "Organization",
    "inc": "Organization",
    "ltd": "Organization",
    "gmbh": "Organization",
    "vendor": "Organization",
    "supplier": "Organization",
    "carrier": "Organization",
    "agency": "Organization",
    "institute": "Organization",
    "university": "Organization",
    "ministry": "Organization",
    "consortium": "Organization",
    "coalition": "Organization",
    "leipzig": "Location",
    "lyon": "Location",
    "berlin": "Location",
    "warsaw": "Location",
    "paris": "Location",
    "london": "Location",
    "france": "Location",
    "germany": "Location",
    "europe": "Location",
    "asia": "Location",
    "america": "Location",
    "baltic": "Location",
    "tablet": "Product",
    "laptop": "Product",
    "smartphone": "Product",
    "device": "Product",
    "bearing": "Product",
    "bearings": "Product",
    "chassis": "Product",
    "chip": "Product",
    "chips": "Product",
    "glass": "Product",
    "paper": "Product",
    "ink": "Product",
    "wire": "Product",
    "tin": "Product",
    "resin": "Product",
    "steel": "Product",
    "reactor": "Product",
    "fleet": "Product",
    "freight": "Product",
    "sensor": "Product",
    "shipments": "Product",
    "inventory": "Product",
    "devices": "Product",
    "technology": "Technology",
    "framework": "Technology",
    "protocol": "Technology",
    "platform": "Technology",
}

_KNOWN_ORG_WORDS = frozenset("acme northwind nordwind helio helios vega bergmann halcyon".split())
_SUPPLY_VERBS = frozenset(
    "supplies provides ships moves manufactures distributes sells serves receives buys purchases sources".split()
)


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


class ExtractedEntity(BaseModel):
    id: str
    name: str
    type: str
    doc_id: str
    chunk_id: str
    properties: dict[str, Any] = Field(default_factory=dict)
    score: float = 1.0


class ExtractedRelation(BaseModel):
    id: str
    source_id: str
    target_id: str
    type: str
    doc_id: str
    chunk_id: str
    properties: dict[str, Any] = Field(default_factory=dict)
    score: float = 1.0


class ExtractionResult(BaseModel):
    entities: list[ExtractedEntity]
    relations: list[ExtractedRelation]
    violations: list[str] = Field(default_factory=list)


class EntityExtractor(Protocol):
    def extract(self, text: str, doc_id: str, chunk_id: str) -> ExtractionResult: ...


class PatternExtractor:
    """Deterministic extractor: proper-noun entities + verb-relation lexicon,
    typed and validated against the default ontology."""

    def __init__(self, registry: OntologyRegistry = DEFAULT_ONTOLOGY) -> None:
        self.registry = registry

    # ------------------------------------------------------------------
    def extract(self, text: str, doc_id: str, chunk_id: str) -> ExtractionResult:
        entities = self._entities(text, doc_id, chunk_id)
        by_name: dict[str, ExtractedEntity] = {_norm(e.name): e for e in entities}
        relations = self._relations(text, entities, by_name, doc_id, chunk_id)
        violations = self._validate(entities, relations)
        return ExtractionResult(entities=entities, relations=relations, violations=violations)

    # ------------------------------------------------------------------
    def _entities(self, text: str, doc_id: str, chunk_id: str) -> list[ExtractedEntity]:
        seen: set[str] = set()
        entities: list[ExtractedEntity] = []
        idx = 0
        for match in _PROP.finditer(text):
            name = match.group(1).strip()
            if name in _SKIP_PROPER:
                continue
            key = _norm(name)
            if key in seen:
                continue
            seen.add(key)
            entities.append(
                ExtractedEntity(
                    id=f"e{idx}",
                    name=name,
                    type=self._entity_type(name),
                    doc_id=doc_id,
                    chunk_id=chunk_id,
                )
            )
            idx += 1
        return entities

    @staticmethod
    def _entity_type(name: str) -> str:
        words = name.lower().split()
        for word in words:
            if word in _ENTITY_HINT:
                return _ENTITY_HINT[word]
        if any(w in _KNOWN_ORG_WORDS for w in words):
            return "Organization"
        return "Person"

    # ------------------------------------------------------------------
    def _relations(
        self,
        text: str,
        entities: list[ExtractedEntity],
        by_name: dict[str, ExtractedEntity],
        doc_id: str,
        chunk_id: str,
    ) -> list[ExtractedRelation]:
        spans = sorted((m.start(), m.end(), _norm(m.group(1).strip())) for m in _PROP.finditer(text))
        relations: list[ExtractedRelation] = []
        ridx = 0

        def add(edge_type: str, src_name: str, tgt_name: str) -> None:
            nonlocal ridx
            src = by_name.get(_norm(src_name))
            tgt = by_name.get(_norm(tgt_name))
            if src is None or tgt is None or src.id == tgt.id:
                return
            relations.append(
                ExtractedRelation(
                    id=f"r{ridx}",
                    source_id=src.id,
                    target_id=tgt.id,
                    type=edge_type,
                    doc_id=doc_id,
                    chunk_id=chunk_id,
                )
            )
            ridx += 1

        for verb in _SUPPLY_VERBS:
            for m in re.finditer(rf"\b{verb}\b", text, re.IGNORECASE):
                pre = self._nearest_before(spans, m.start())
                post = self._nearest_after(spans, m.end())
                if not pre or not post:
                    continue
                segment = text[m.end() : post[1]].lower()
                if "from" in segment:
                    add("provides", post[2], pre[2])
                else:
                    add("provides", pre[2], post[2])

        for m in re.finditer(r"\bacquired\b", text, re.IGNORECASE):
            pre = self._nearest_before(spans, m.start())
            post = self._nearest_after(spans, m.end())
            if pre and post:
                add("acquired_by", post[2], pre[2])

        for m in re.finditer(r"\b(?:developed|develops|develop|created|built)\b", text, re.IGNORECASE):
            pre = self._nearest_before(spans, m.start())
            post = self._nearest_after(spans, m.end())
            if pre and post:
                add("developed_by", post[2], pre[2])

        for m in re.finditer(r"\bemploys\b", text, re.IGNORECASE):
            pre = self._nearest_before(spans, m.start())
            post = self._nearest_after(spans, m.end())
            if pre and post:
                add("employs", pre[2], post[2])

        for m in re.finditer(r"\buses\b", text, re.IGNORECASE):
            pre = self._nearest_before(spans, m.start())
            post = self._nearest_after(spans, m.end())
            if pre and post:
                add("uses", pre[2], post[2])

        for m in re.finditer(r"\blocated in\b", text, re.IGNORECASE):
            pre = self._nearest_before(spans, m.start())
            post = self._nearest_after(spans, m.end())
            if pre and post:
                add("located_in", pre[2], post[2])

        return relations

    @staticmethod
    def _nearest_before(spans: list[tuple[int, int, str]], pos: int) -> tuple[int, int, str] | None:
        before = [s for s in spans if s[1] <= pos]
        return before[-1] if before else None

    @staticmethod
    def _nearest_after(spans: list[tuple[int, int, str]], pos: int) -> tuple[int, int, str] | None:
        after = [s for s in spans if s[0] >= pos]
        return after[0] if after else None

    # ------------------------------------------------------------------
    def _validate(self, entities: list[ExtractedEntity], relations: list[ExtractedRelation]) -> list[str]:
        violations: list[str] = []
        by_id = {e.id: e for e in entities}
        for e in entities:
            violations.extend(self.registry.validate_entity(e.type, e.properties))
        for r in relations:
            src = by_id.get(r.source_id)
            tgt = by_id.get(r.target_id)
            violations.extend(
                self.registry.validate_relation(
                    r.type, src.type if src else "?", tgt.type if tgt else "?", r.properties
                )
            )
        return violations


class InstructorExtractor:
    """Real typed extractor over the LLM provider (A-K-37).

    The prompt carries the ontology as the type constraint; the provider
    negotiates structured output. Instructor, when installed, patches the
    HTTP client for stricter schema enforcement — never required.
    """

    def __init__(self, provider: Any, registry: OntologyRegistry = DEFAULT_ONTOLOGY) -> None:
        self.provider = provider
        self.registry = registry

    def extract(self, text: str, doc_id: str, chunk_id: str) -> ExtractionResult:
        from pydantic import BaseModel, Field

        class InstructorEntity(BaseModel):
            name: str = Field(description="entity surface name")
            type: str = Field(description="one of the registered entity types")
            properties: dict[str, Any] = Field(default_factory=dict)

        class InstructorRelation(BaseModel):
            source: str = Field(description="source entity name")
            target: str = Field(description="target entity name")
            type: str = Field(description="one of the registered edge types")

        class InstructorDoc(BaseModel):
            entities: list[InstructorEntity] = Field(default_factory=list)
            relations: list[InstructorRelation] = Field(default_factory=list)

        client = self.provider
        try:  # instructor is optional; patch when present
            import instructor  # type: ignore

            client = instructor.from_openai(self.provider._http())  # type: ignore[attr-defined]
        except (ImportError, AttributeError):
            pass

        prompt = (
            f"Extract entities and typed relations from the text below.\n"
            f"The ONLY allowed entity types are: {', '.join(self.registry.entity_names())}.\n"
            f"The ONLY allowed relation types are: {', '.join(self.registry.edge_names())}, where "
            f"each relation's source/target entity types must match the edge's declared endpoint "
            f"types (schema: {self.registry.as_dict()}).\n\n"
            f"Text:\n{text}"
        )
        try:
            parsed: InstructorDoc = client.structured(InstructorDoc, prompt)
        except AttributeError:
            parsed = self.provider.structured(InstructorDoc, prompt)

        by_name: dict[str, ExtractedEntity] = {}
        entities: list[ExtractedEntity] = []
        relations: list[ExtractedRelation] = []
        for i, e in enumerate(parsed.entities):
            entity = ExtractedEntity(
                id=f"e{i}",
                name=e.name,
                type=e.type,
                doc_id=doc_id,
                chunk_id=chunk_id,
                properties=dict(e.properties),
            )
            entities.append(entity)
            by_name[_norm(e.name)] = entity
        for i, r in enumerate(parsed.relations):
            src = by_name.get(_norm(r.source))
            tgt = by_name.get(_norm(r.target))
            if src is None or tgt is None:
                continue
            relations.append(
                ExtractedRelation(
                    id=f"r{i}",
                    source_id=src.id,
                    target_id=tgt.id,
                    type=r.type,
                    doc_id=doc_id,
                    chunk_id=chunk_id,
                    properties=dict(r.properties),
                )
            )
        violations = self._validate(entities, relations)
        return ExtractionResult(entities=entities, relations=relations, violations=violations)

    def _validate(self, entities: list[ExtractedEntity], relations: list[ExtractedRelation]) -> list[str]:
        return PatternExtractor(self.registry)._validate(entities, relations)
