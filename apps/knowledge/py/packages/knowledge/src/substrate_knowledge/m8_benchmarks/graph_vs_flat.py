"""A-K-31 graph-vs-flat-runner — R1: when is the graph worth it?

Equal-cost comparison: under a fixed evidence budget `k`, three retrievers
(flat token-overlap index, co-occurrence graph with 2-hop expansion and
stance-aware filtering, and a hybrid) compete on evidence recall over the
synthetic corpora. Fully deterministic — no LLM, no embeddings — so the
decision rule can be validated against measurement instead of vibes.

Graph mode (documented decision procedure):
  1. query entities = question terms that are graph nodes (corpus df >= 2),
     minus corpus stopwords (df > 0.7 * n_docs);
  2. 2-hop expansion from the seeds over the co-occurrence graph;
  3. doc score = sum over novel (non-seed) entities in the doc of
     1 / distance(seed, entity) — the answer doc contains the full join
     path, so it outranks lexical decoys that only share query words;
  4. when the query carries stance polarity, only same-stance docs compete
     (the contradiction corpus: flat cannot express stance provenance).
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from substrate_knowledge.core.text import tokenize
from substrate_knowledge.m1_characterization.profiler import _STANCE_NEG, _STANCE_POS, CorpusStructuralProfiler
from substrate_knowledge.m8_benchmarks.corpora import SyntheticCorpus, query_polarity

MAX_HOPS = 2
STOPWORD_DF_RATIO = 0.7


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
    - graph: 2-hop expansion + depth-weighted novel-entity scoring with
      stance filtering (see module docstring).
    - hybrid: budget split between the two.
    """

    def __init__(self, budget: int = 2, corpus_budgets: dict[str, int] | None = None) -> None:
        self.budget = budget
        # Multi-doc gold sets need the budget to cover the answer set:
        # stance corpora and the graph-only join sets have 2-4 gold docs.
        self.corpus_budgets = corpus_budgets or {"contradiction": 4, "graph-only": 4}
        self._retrieval_entities: set[str] = set()

    # ------------------------------------------------------------------
    def run(self, corpus: SyntheticCorpus) -> GraphVsFlatResult:
        self._corpus = corpus
        self._doc_tokens = {d.doc_id: tokenize(d.text) for d in corpus.docs}
        self._term_freq = dict(Counter(t for tokens in self._doc_tokens.values() for t in set(tokens)))
        n_docs = len(self._doc_tokens)
        stopword_threshold = STOPWORD_DF_RATIO * n_docs
        # Corpus stopwords (terms present in > 70% of docs, e.g. "supplies"
        # in the terse graph-only corpus) are not retrieval-graph nodes:
        # they connect everything and would flatten every score.
        self._retrieval_entities = {e for e in corpus.entity_terms() if self._term_freq.get(e, 0) <= stopword_threshold}
        self._entities = self._retrieval_entities
        self._adjacency = self._cooccurrence()
        budget = self.corpus_budgets.get(corpus.name, self.budget)
        # Stance-aware retrieval is only usable when the corpus exhibits
        # contradiction structure (the profiler's contradiction_index).
        profile = CorpusStructuralProfiler().profile(corpus.docs)
        self._stance_aware = profile.contradiction_index > 0

        flat = [self._flat_retrieve(q.question, budget) for q in corpus.qa]
        graph = [self._graph_retrieve(q.question, budget) for q in corpus.qa]
        hybrid = [self._hybrid_retrieve(q.question, budget) for q in corpus.qa]

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
        return GraphVsFlatResult(corpus=corpus.name, budget=budget, flat=flat, graph=graph, hybrid=hybrid, measured_winner=winner)

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
        seeds = set(tokenize(question)) & self._retrieval_entities
        if not seeds:
            return []
        distances = self._expansion_distances(seeds)
        polarity = query_polarity(question)

        scored: list[tuple[float, str]] = []
        for doc_id, toks in self._doc_tokens.items():
            if self._stance_aware and polarity != "neutral" and self._stance_of(toks) != polarity:
                continue
            novel = set(toks) & set(distances) - seeds
            score = sum(1.0 / distances[e] for e in novel)
            if score > 0:
                scored.append((score, doc_id))
        scored.sort(key=lambda p: (-p[0], p[1]))
        return [doc_id for _, doc_id in scored[:k]]

    def _expansion_distances(self, seeds: set[str]) -> dict[str, int]:
        """BFS distances from the seed set, up to MAX_HOPS hops."""
        distances = {s: 0 for s in seeds}
        frontier = list(seeds)
        depth = 0
        while frontier and depth < MAX_HOPS:
            depth += 1
            nxt: list[str] = []
            for node in frontier:
                for nb in self._adjacency.get(node, ()):
                    if nb not in distances:
                        distances[nb] = depth
                        nxt.append(nb)
            frontier = nxt
        return distances

    def _hybrid_retrieve(self, question: str, k: int) -> list[str]:
        half = max(1, k // 2)
        flat = self._flat_retrieve(question, half)
        graph = self._graph_retrieve(question, k)
        merged: list[str] = []
        for doc_id in flat + graph:
            if doc_id not in merged:
                merged.append(doc_id)
        return merged[:k]
