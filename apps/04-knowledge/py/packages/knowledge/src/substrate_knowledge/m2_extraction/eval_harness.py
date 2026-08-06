"""A-K-07 extraction-eval-harness.

Precision / recall / F1 for entities and relations plus type-violation rate
per labeled slice, and a continuous corpus score (gold-weighted means).
The harness never calls an LLM: gold slices are compared against whatever
extractor produced the result, which keeps evals deterministic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from substrate_knowledge.m2_extraction.extractor import ExtractionResult
from substrate_knowledge.m2_extraction.golden_slices import GoldSlice


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


@dataclass
class SliceEvaluation:
    slice_id: str
    n_gold_entities: int
    n_extracted_entities: int
    entity_precision: float
    entity_recall: float
    entity_f1: float
    n_gold_relations: int
    relation_precision: float
    relation_recall: float
    relation_f1: float
    type_violation_rate: float
    n_type_violations: int

    def to_dict(self) -> dict:
        return {
            "slice_id": self.slice_id,
            "n_gold_entities": self.n_gold_entities,
            "n_extracted_entities": self.n_extracted_entities,
            "entity_precision": round(self.entity_precision, 4),
            "entity_recall": round(self.entity_recall, 4),
            "entity_f1": round(self.entity_f1, 4),
            "n_gold_relations": self.n_gold_relations,
            "relation_precision": round(self.relation_precision, 4),
            "relation_recall": round(self.relation_recall, 4),
            "relation_f1": round(self.relation_f1, 4),
            "type_violation_rate": round(self.type_violation_rate, 4),
            "n_type_violations": self.n_type_violations,
        }


@dataclass
class EvalReport:
    slices: list[SliceEvaluation] = field(default_factory=list)
    continuous: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "slices": [s.to_dict() for s in self.slices],
            "continuous": {k: round(v, 4) for k, v in self.continuous.items()},
        }


class ExtractionEvalHarness:
    """Deterministic eval over labeled slices."""

    # ------------------------------------------------------------------
    def evaluate(self, gold: GoldSlice, result: ExtractionResult) -> SliceEvaluation:
        gold_entities = {_norm(e.name) for e in gold.entities}
        gold_rels = {(_norm(r.source), _norm(r.target), r.type) for r in gold.relations}
        extracted_entities = {_norm(e.name) for e in result.entities}
        name_by_id = {e.id: _norm(e.name) for e in result.entities}
        extracted_rels = {
            (_norm(name_by_id.get(r.source_id, r.source_id)), _norm(name_by_id.get(r.target_id, r.target_id)), r.type)
            for r in result.relations
        }

        n_ge = len(gold_entities)
        n_ee = len(extracted_entities)
        ent_hits = len(gold_entities & extracted_entities)
        ent_p = ent_hits / n_ee if n_ee else 0.0
        ent_r = ent_hits / n_ge if n_ge else 0.0
        ent_f1 = 2 * ent_p * ent_r / (ent_p + ent_r) if ent_p + ent_r > 0 else 0.0

        n_gr = len(gold_rels)
        n_er = len(extracted_rels)
        rel_hits = len(gold_rels & extracted_rels)
        rel_p = rel_hits / n_er if n_er else 0.0
        rel_r = rel_hits / n_gr if n_gr else 0.0
        rel_f1 = 2 * rel_p * rel_r / (rel_p + rel_r) if rel_p + rel_r > 0 else 0.0

        n_violations = len(result.violations)
        n_items = len(result.entities) + len(result.relations)
        viol_rate = n_violations / n_items if n_items else 0.0

        return SliceEvaluation(
            slice_id=gold.slice_id,
            n_gold_entities=n_ge,
            n_extracted_entities=n_ee,
            entity_precision=ent_p,
            entity_recall=ent_r,
            entity_f1=ent_f1,
            n_gold_relations=n_gr,
            relation_precision=rel_p,
            relation_recall=rel_r,
            relation_f1=rel_f1,
            type_violation_rate=viol_rate,
            n_type_violations=n_violations,
        )

    # ------------------------------------------------------------------
    def evaluate_slices(self, golds: list[GoldSlice], extractor: object) -> EvalReport:
        """Run the extractor over every golden slice; continuous score is the
        gold-weighted mean of the per-slice metrics (weight = gold item count)."""
        report = EvalReport()
        for gold in golds:
            result = extractor.extract(gold.text, gold.slice_id, f"{gold.slice_id}:0")  # type: ignore[attr-defined]
            report.slices.append(self.evaluate(gold, result))
        self._continuous(report)
        return report

    @staticmethod
    def _continuous(report: EvalReport) -> None:
        slices = report.slices
        weights = [max(1, s.n_gold_entities + s.n_gold_relations) for s in slices]
        total = sum(weights) or 1
        report.continuous = {
            "entity_precision": sum(w * s.entity_precision for w, s in zip(weights, slices)) / total,
            "entity_recall": sum(w * s.entity_recall for w, s in zip(weights, slices)) / total,
            "entity_f1": sum(w * s.entity_f1 for w, s in zip(weights, slices)) / total,
            "relation_precision": sum(w * s.relation_precision for w, s in zip(weights, slices)) / total,
            "relation_recall": sum(w * s.relation_recall for w, s in zip(weights, slices)) / total,
            "relation_f1": sum(w * s.relation_f1 for w, s in zip(weights, slices)) / total,
            "type_violation_rate": sum(w * s.type_violation_rate for w, s in zip(weights, slices)) / total,
        }
