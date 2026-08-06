"""A-K-12 similarity-scorer — Fellegi-Sunter + embedding cosine fusion.

The Fellegi-Sunter math is implemented here directly (no Splink/DuckDB
required): for each comparator, m = P(agree | match) and u = P(agree |
non-match); the weight of an agreement pattern is the sum of the log-odds
ratio per comparator. Embedding cosine fuses into the final score as a
centered additive term.

Properties that tests assert:
  - all-agree patterns score higher than none-agree patterns;
  - the weight of two agreeing comparators equals the sum of the two
    single-comparator weights (log-linearity);
  - same-canonical-name records score above records with different names.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from substrate_knowledge.core.text import cosine
from substrate_knowledge.m3_resolution.blocker import EntityRecord, canonical_name

DEFAULT_M_PROBS: tuple[float, ...] = (0.85, 0.80, 0.60, 0.55)  # name, type, source, date
DEFAULT_U_PROBS: tuple[float, ...] = (0.05, 0.20, 0.30, 0.40)
COMPARATORS = ("name", "type", "source", "date")


@dataclass
class PairScore:
    left_id: str
    right_id: str
    comparisons: dict[str, bool]
    fellegi_sunter_weight: float
    cosine: float
    fused_score: float

    def to_dict(self) -> dict:
        return {
            "left_id": self.left_id,
            "right_id": self.right_id,
            "comparisons": self.comparisons,
            "fellegi_sunter_weight": round(self.fellegi_sunter_weight, 4),
            "cosine": round(self.cosine, 4),
            "fused_score": round(self.fused_score, 4),
        }


class FelgiSunterScorer:
    def __init__(
        self,
        m_probs: tuple[float, ...] = DEFAULT_M_PROBS,
        u_probs: tuple[float, ...] = DEFAULT_U_PROBS,
        fusion_lambda: float = 1.0,
        cosine_threshold: float = 0.5,
    ) -> None:
        if not (len(m_probs) == len(u_probs) == len(COMPARATORS)):
            raise ValueError("m/u probability vectors must match the comparator count")
        self.m_probs = m_probs
        self.u_probs = u_probs
        self.fusion_lambda = fusion_lambda
        self.cosine_threshold = cosine_threshold

    # ------------------------------------------------------------------
    # Fellegi-Sunter core
    # ------------------------------------------------------------------
    def agreement_weight(self, agreements: tuple[bool, ...]) -> float:
        """Total weight of an agreement pattern (log-sum over comparators)."""
        if len(agreements) != len(COMPARATORS):
            raise ValueError("agreement vector must match comparator count")
        weight = 0.0
        for agree, m, u in zip(agreements, self.m_probs, self.u_probs):
            if agree:
                weight += math.log(m / u)
            else:
                weight += math.log((1.0 - m) / (1.0 - u))
        return weight

    # ------------------------------------------------------------------
    def compare(self, left: EntityRecord, right: EntityRecord) -> tuple[dict[str, bool], float]:
        """Per-comparator agreements + cosine between embeddings."""
        agreements = {
            "name": canonical_name(left.name) == canonical_name(right.name),
            "type": canonical_name(left.type) == canonical_name(right.type),
            "source": canonical_name(left.source) == canonical_name(right.source),
            "date": left.date == right.date,
        }
        sim = 0.0
        if getattr(left, "embedding", None) is not None and getattr(right, "embedding", None) is not None:
            sim = cosine(np.asarray(left.embedding, dtype=float), np.asarray(right.embedding, dtype=float))
        return agreements, sim

    def score_pair(self, left: EntityRecord, right: EntityRecord) -> PairScore:
        agreements, sim = self.compare(left, right)
        pattern = tuple(agreements[c] for c in COMPARATORS)
        fs_weight = self.agreement_weight(pattern)
        fused = fs_weight + self.fusion_lambda * (sim - self.cosine_threshold)
        return PairScore(
            left_id=left.entity_id,
            right_id=right.entity_id,
            comparisons=agreements,
            fellegi_sunter_weight=fs_weight,
            cosine=sim,
            fused_score=fused,
        )

    def score_all_pairs(self, records: list[EntityRecord]) -> list[PairScore]:
        scores = []
        for i in range(len(records)):
            for j in range(i + 1, len(records)):
                scores.append(self.score_pair(records[i], records[j]))
        return scores
