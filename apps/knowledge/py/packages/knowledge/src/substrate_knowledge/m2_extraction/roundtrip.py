"""A-K-08 round-trip-validator.

Extract -> re-embed -> verify relation recoverability. A relation is
recoverable from its source chunk when both endpoints are grounded in the
text: every surface token of both endpoint names appears in the chunk
(exact, deterministic containment), OR the endpoint embedding is close to
the chunk embedding (the cosine path, which matters once embeddings are
semantic — with hashing-trick embeddings, token collisions can flip small
cosines, so containment is the primary signal).

Hallucinated endpoints — names the extractor invented that never appear in
the text — fail containment and score near-zero cosine: the cheap,
embedding-free-of-LLM fidelity check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from substrate_knowledge.core.text import cosine, hash_embed, tokenize
from substrate_knowledge.m2_extraction.extractor import ExtractionResult

Embedder = Callable[[str], np.ndarray]


@dataclass
class RoundTripReport:
    chunk_id: str
    n_relations: int
    recoverable_relations: int
    recoverability: float
    relation_scores: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "n_relations": self.n_relations,
            "recoverable_relations": self.recoverable_relations,
            "recoverability": round(self.recoverability, 4),
            "relation_scores": self.relation_scores,
        }


class RoundTripValidator:
    def __init__(self, embedder: Embedder = hash_embed, threshold: float = 0.15) -> None:
        self.embedder = embedder
        self.threshold = threshold

    def verify(self, result: ExtractionResult, chunk_text: str) -> RoundTripReport:
        entities = {e.id: e for e in result.entities}
        chunk_vec = self.embedder(chunk_text)
        chunk_tokens = set(tokenize(chunk_text))
        scores = []
        recoverable = 0
        for rel in result.relations:
            src = entities.get(rel.source_id)
            tgt = entities.get(rel.target_id)
            if src is None or tgt is None:
                continue
            src_cosine = cosine(self.embedder(src.name), chunk_vec)
            tgt_cosine = cosine(self.embedder(tgt.name), chunk_vec)
            score = min(src_cosine, tgt_cosine)
            contained = set(tokenize(src.name)) <= chunk_tokens and set(tokenize(tgt.name)) <= chunk_tokens
            ok = contained or score >= self.threshold
            recoverable += int(ok)
            scores.append(
                {
                    "relation": rel.type,
                    "source": src.name,
                    "target": tgt.name,
                    "score": round(score, 4),
                    "contained": bool(contained),
                    "recoverable": bool(ok),
                }
            )
        n = len(result.relations)
        return RoundTripReport(
            chunk_id=result.relations[0].chunk_id if result.relations else "",
            n_relations=n,
            recoverable_relations=recoverable,
            recoverability=recoverable / n if n else 0.0,
            relation_scores=scores,
        )
