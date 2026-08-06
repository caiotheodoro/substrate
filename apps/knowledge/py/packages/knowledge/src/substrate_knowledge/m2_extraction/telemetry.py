"""A-K-09 extraction-telemetry-store.

Per-doc and per-slice extraction scores, violations, and a continuous
corpus score. Backed by the generic KV Store: in-memory for tests/CLI,
Postgres for the compose stack (one table, zero migrations beyond the
base KV schema).
"""

from __future__ import annotations

from typing import Any

from substrate_knowledge.core.storage import Store
from substrate_knowledge.m2_extraction.eval_harness import SliceEvaluation


class ExtractionTelemetryStore:
    def __init__(self, store: Store) -> None:
        self.store = store

    # ------------------------------------------------------------------
    def record_slice(self, evaluation: SliceEvaluation) -> None:
        self.store.put(f"telemetry:slice:{evaluation.slice_id}", evaluation.to_dict())

    def record_doc(self, doc_id: str, *, n_entities: int, n_relations: int, n_violations: int, score: float = 0.0) -> None:
        self.store.put(
            f"telemetry:doc:{doc_id}",
            {
                "doc_id": doc_id,
                "n_entities": n_entities,
                "n_relations": n_relations,
                "n_violations": n_violations,
                "score": score,
            },
        )

    def record_violation(self, doc_id: str, violation: str) -> None:
        existing = self.store.get(f"telemetry:doc:{doc_id}") or {}
        violations = list(existing.get("violations", []))
        violations.append(violation)
        existing["violations"] = violations[-100:]
        existing.setdefault("doc_id", doc_id)
        self.store.put(f"telemetry:doc:{doc_id}", existing)

    # ------------------------------------------------------------------
    def slice_score(self, slice_id: str) -> dict[str, Any] | None:
        return self.store.get(f"telemetry:slice:{slice_id}")

    def doc_scores(self) -> list[dict[str, Any]]:
        return [value for _, value in self.store.scan("telemetry:doc:")]

    def continuous_score(self) -> dict[str, float]:
        slices = [value for _, value in self.store.scan("telemetry:slice:")]
        if not slices:
            return {"n_slices": 0.0, "entity_precision": 0.0, "entity_recall": 0.0, "relation_f1": 0.0}
        n = len(slices)
        return {
            "n_slices": float(n),
            "entity_precision": sum(s["entity_precision"] for s in slices) / n,
            "entity_recall": sum(s["entity_recall"] for s in slices) / n,
            "relation_f1": sum(s["relation_f1"] for s in slices) / n,
        }
