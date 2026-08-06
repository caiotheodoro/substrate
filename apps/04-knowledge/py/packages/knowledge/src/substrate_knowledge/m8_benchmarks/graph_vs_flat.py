"""A-K-31 graph-vs-flat-runner — R1: when is the graph worth it?

Equal-cost comparison: under a fixed evidence budget `k`, three retrievers
(flat token-overlap index, co-occurrence graph with 2-hop expansion and
stance-aware filtering, and a hybrid) compete on evidence recall over the
synthetic corpora. Fully deterministic — no LLM, no embeddings — so the
decision rule can be validated against measurement instead of vibes.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from substrate_knowledge.core.text import tokenize
from substrate_knowledge.m1_characterization.profiler import _STANCE_NEG, _STANCE_POS, CorpusStructuralProfiler
from substrate_knowledge.m8_benchmarks.corpora import SyntheticCorpus, query_polarity


@dataclass
class RetrievalModeResult:
    evidence_recall: float
    precision: float
    correct: int
    total: int


@dataclass
class GraphVsFlatResult:
    corpus: str
    budget: int
    flat: RetrievalModeResult
    graph: RetrievalModeResult
    hybrid: RetrievalModeResult
    measured_winner: str = "tie"

    def to_dict(self) -> dict:
        winner = self.measured_winner
        if winner == "graph" and self.hybrid.evidence_recall == self.graph.evidence_recall:
            winner = "vector+graph"
        if winner == "tie":
            winner = "tie"
        return {
            "corpus": self.corpus,
            "budget": self.budget,
            "measured_winner": winner,
            "flat": {"evidence_recall": round(self.flat.evidence_recall, 3), "precision": round(self.flat.precision, 3)},
            "graph": {"evidence_recall": round(self.graph.evidence_recall, 3), "precision": round(self.graph.precision, 3)},
            "hybrid": {"evidence_recall": round(self.hybrid.evidence_recall, 3), "precision": round(self.hybrid.precision, 3)},
        }


class GraphVsFlatRunner:
    """Three retrievers over the same corpus at the same budget.

    - flat: token-overlap scoring over documents (rare-term bonus).
    - graph: co-occurrence graph; query entities -> 2-hop expansion; stance
      filtering when the query carries polarity; evidence = docs containing
      expanded entities, scored by matched-entity count.
    - hybrid: budget split between the two.
    """

    def __init__(self, budget: int = 4) -> None:
        self.budget = budget

    # ------------------------------------------------------------------
    def run(self, corpus: SyntheticCorpus) -> GraphVsFlatResult:
        self._corpus = corpus
        self._doc_tokens = {d.doc_id: tokenize(d.text) for d in corpus.docs}
        self._term_freq = dict(Counter(t for tokens in self._doc_tokens.values() for t in set(tokens)))
        self._entities = corpus.entity_terms()
        self._adjacency = self._cooccurrence()

        flat = [self._flat_retrieve(q.question, self.budget) for q in corpus.qa]
        graph = [self._graph_retrieve(q.question, self.budget) for q in corpus.qa]
        hybrid = [self._hybrid_retrieve(q.question, self.budget) for q in corpus.qa]

        def summarize(retrieved_list: list[list[str]]) -> RetrievalModeResult:
            correct = 0
            prec_total = 0.0
            for q, retrieved in zip(corpus.qa, retrieved_list):
                gold = set(q.evidence_docs)
                hits = gold & set(retrieved)
                if gold and gold.issubset(set(retrieved)):
                    correct += 1
                prec_total += len(hits) / max(1, len(retrieved))
            n = max(1, len(corpus.qa))
            return RetrievalModeResult(correct / n, prec_total / n, correct, len(corpus.qa))

        flat = summarize(flat)
        graph = summarize(graph)
        hybrid = summarize(hybrid)

        scores = {"flat": flat.evidence_recall, "graph": graph.evidence_recall, "hybrid": hybrid.evidence_recall}
        best = max(scores, key=scores.get)
        winner = best if list(scores.values()).count(scores[best]) == 1 else "tie"
        return GraphVsFlatResult(corpus=corpus.name, budget=self.budget, flat=flat, graph=graph, hybrid=hybrid, measured_winner=winner)

    # ------------------------------------------------------------------
    def _cooccurrence(self) -> dict[str, set[str]]:
        entities = sorted(self._entities)
        adjacency: dict[str, set[str]] = {e: set() for e in entities}
        for doc in self._corpus.docs:
            de = [e for e in entities if e in self._doc_tokens[doc.doc_id]]
            for i, a in enumerate(de):
                for b in de[i + 1 :]:
                    adjacency[a].add(b)
                    adjacency[b].add(a)
        return adjacency

    @staticmethod
    def _stance_of(tokens: list[str]) -> str:
        pos = sum(1 for t in tokens if t in _STANCE_POS)
        neg = sum(1 for t in tokens if t in _STANCE_NEG)
        return CorpusStructuralProfiler._stance(float(pos - neg))

    def _flat_retrieve(self, question: str, k: int) -> list[str]:
        q_terms = set(tokenize(question))
        scored: list[tuple[float, str]] = []
        for doc_id, toks in self._doc_tokens.items():
            overlap = q_terms & set(toks)
            if not overlap:
                continue
            score = sum(1.0 / math.log1p(self._term_freq.get(t, 2)) for t in overlap)
            scored.append((score, doc_id))
        scored.sort(key=lambda p: (-p[0], p[1]))
        return [doc_id for _, doc_id in scored[:k]]

    def _graph_retrieve(self, question: str, k: int) -> list[str]:
        q_terms = set(tokenize(question)) & self._entities
        if not q_terms:
            return []
        polarity = query_polarity(question)
        reached: set[str] = set(q_terms)
        for seed in q_terms:
            for nb in self._adjacency.get(seed, ()):
                reached.add(nb)
                for nnb in self._adjacency.get(nb, ()):
                    reached.add(nnb)
        reached -= q_terms
        if not reached:
            return []

        stance: dict[str, str] | None = None
        if polarity != "neutral":
            stance = {doc_id: self._stance_of(toks) for doc_id, toks in self._doc_tokens.items()}

        scored: list[tuple[float, str]] = []
        for doc_id, toks in self._doc_tokens.items():
            if stance is not None and stance[doc_id] != polarity:
                continue
            matched = len(reached & set(toks))
            if matched == 0:
                continue
            scored.append((float(matched), doc_id))
        scored.sort(key=lambda p: (-p[0], p[1]))
        return [doc_id for _, doc_id in scored[:k]]

    def _hybrid_retrieve(self, question: str, k: int) -> list[str]:
        half = max(1, k // 2)
        flat = self._flat_retrieve(question, half)
        graph = self._graph_retrieve(question, k)
        merged: list[str] = []
        for doc_id in flat + graph:
            if doc_id not in merged:
                merged.append(doc_id)
        return merged[:k]