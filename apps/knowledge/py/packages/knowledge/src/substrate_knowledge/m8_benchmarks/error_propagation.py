"""A-K-32 extraction-error-propagation — R2.

If extraction is wrong on x% of entities and y% of relations, what fraction
of correct queries still resolve to correct evidence? Simulation over the
multi-hop corpus: per trial, each gold entity of the evidence chain survives
with probability (1 - p_entity) and each co-occurrence relation inside a
gold evidence doc survives with probability (1 - p_relation); a query
resolves correctly when all its evidence entities survive and the induced
subgraph stays connected. Fully deterministic under a seed — this is the R2
curve, measured, not hand-waved.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable

from substrate_knowledge.core.text import tokenize
from substrate_knowledge.m8_benchmarks.corpora import build_multi_hop_corpus

DEFAULT_ERROR_RATES = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6)


@dataclass
class PropagationPoint:
    error_rate: float
    correct_resolution: float
    n_queries: int

    def to_dict(self) -> dict:
        return {
            "error_rate": self.error_rate,
            "correct_resolution": round(self.correct_resolution, 4),
            "n_queries": self.n_queries,
        }


class ErrorPropagationRunner:
    def __init__(
        self,
        seed: int = 7,
        n_queries_per_rate: int = 200,
        corpus_factory: Callable = build_multi_hop_corpus,
        relation_error_ratio: float = 1.0,
    ) -> None:
        self.seed = seed
        self.n_queries_per_rate = n_queries_per_rate
        self.corpus_factory = corpus_factory
        self.relation_error_ratio = relation_error_ratio

    # ------------------------------------------------------------------
    def run(self, error_rates: tuple[float, ...] = DEFAULT_ERROR_RATES) -> list[PropagationPoint]:
        corpus = self.corpus_factory()
        chains = [self._evidence_chain(q.evidence_docs) for q in corpus.qa]
        points: list[PropagationPoint] = []
        for rate in error_rates:
            rng = random.Random(self.seed + int(rate * 100))
            resolved = 0
            for _ in range(self.n_queries_per_rate):
                chain = rng.choice(chains)
                if self._trial_resolves(chain, rate, rng):
                    resolved += 1
            points.append(PropagationPoint(rate, resolved / self.n_queries_per_rate, self.n_queries_per_rate))
        return points

    # ------------------------------------------------------------------
    @staticmethod
    def _evidence_chain(evidence_docs: list[str]) -> dict:
        """Entities + intra-doc co-occurrence pairs for one question's gold
        evidence. Entities are tokens appearing in >= 2 docs (stable)."""
        from substrate_knowledge.m1_characterization.profiler import MIN_ENTITY_FREQ

        corpus = build_multi_hop_corpus()
        tokens_by_doc = {d.doc_id: tokenize(d.text) for d in corpus.docs}
        doc_freq = {}
        for toks in tokens_by_doc.values():
            for t in set(toks):
                doc_freq[t] = doc_freq.get(t, 0) + 1
        entities = {t for t, f in doc_freq.items() if f >= MIN_ENTITY_FREQ}

        chain_entities: set[str] = set()
        pairs: list[tuple[str, str]] = []
        for doc_id in evidence_docs:
            toks = set(tokens_by_doc.get(doc_id, []))
            doc_entities = sorted(entities & toks)
            chain_entities.update(doc_entities)
            for i in range(len(doc_entities)):
                for j in range(i + 1, len(doc_entities)):
                    pairs.append((doc_entities[i], doc_entities[j]))
        return {"entities": chain_entities, "pairs": pairs}

    def _trial_resolves(self, chain: dict, error_rate: float, rng: random.Random) -> bool:
        p_entity = error_rate
        p_relation = error_rate * self.relation_error_ratio
        survivors = {e for e in chain["entities"] if rng.random() > p_entity}
        if survivors != chain["entities"]:
            return False
        surviving_pairs = [p for p in chain["pairs"] if rng.random() > p_relation]
        if not surviving_pairs:
            return len(chain["entities"]) <= 1
        adjacency: dict[str, set[str]] = {e: set() for e in survivors}
        for a, b in surviving_pairs:
            adjacency[a].add(b)
            adjacency[b].add(a)
        start = next(iter(survivors))
        seen = {start}
        stack = [start]
        while stack:
            node = stack.pop()
            for nb in adjacency.get(node, ()):
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        return len(seen) == len(survivors)
