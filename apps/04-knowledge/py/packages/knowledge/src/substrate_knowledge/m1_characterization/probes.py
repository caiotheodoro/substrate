"""A-K-04 property-probes.

Standalone, testable probes for the three structural properties that gate
graph justification: multi-hop reachability, contradiction pairs, and stance
labeling. These are the measurable tests behind the decision rule.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from substrate_knowledge.core.text import tokenize
from substrate_knowledge.m1_characterization.profiler import (
    MIN_ENTITY_FREQ,
    _STANCE_NEG,
    _STANCE_POS,
    CorpusDocument,
    CorpusStructuralProfiler,
)


@dataclass
class ContradictionPair:
    topic: str
    doc_a: str
    doc_b: str
    polarity_a: float
    polarity_b: float


class PropertyProbes:
    """Deterministic probes over a corpus. LLM-backed stance labeling is a
    drop-in replacement behind the same three methods (v2)."""

    def __init__(self) -> None:
        self._profiler = CorpusStructuralProfiler()

    def multi_hop_reachability(self, docs: list[CorpusDocument], max_hops: int = 2) -> float:
        """Fraction of entity pairs reachable in exactly `max_hops` hops
        (a path through an intermediate entity — the join a flat index can't do)."""
        profile = self._profiler.profile(docs)
        if max_hops == 2:
            return profile.multi_hop_index
        tokens_by_doc = {d.doc_id: tokenize(d.text) for d in docs}
        doc_freq = Counter(t for tokens in tokens_by_doc.values() for t in set(tokens))
        entities = sorted(t for t, f in doc_freq.items() if f >= MIN_ENTITY_FREQ)
        adjacency: dict[str, set[str]] = {e: set() for e in entities}
        for doc in docs:
            de = [e for e in entities if e in tokens_by_doc[doc.doc_id]]
            for i, a in enumerate(de):
                for b in de[i + 1 :]:
                    adjacency[a].add(b)
                    adjacency[b].add(a)
        sample = entities[:80]
        reachable = 0
        total = 0
        for u in sample:
            dist = CorpusStructuralProfiler._bfs(u, adjacency, max_depth=max_hops)
            for v in sample:
                if v == u:
                    continue
                total += 1
                if dist.get(v) == max_hops:
                    reachable += 1
        return reachable / total if total else 0.0

    def contradiction_pairs(self, docs: list[CorpusDocument]) -> list[ContradictionPair]:
        """Every pair of documents that take opposite stances on a shared topic."""
        tokens_by_doc = {d.doc_id: tokenize(d.text) for d in docs}
        doc_freq = Counter(t for tokens in tokens_by_doc.values() for t in set(tokens))
        entity_docs: dict[str, set[str]] = defaultdict(set)
        for doc in docs:
            for t in set(tokens_by_doc[doc.doc_id]):
                if doc_freq[t] >= MIN_ENTITY_FREQ:
                    entity_docs[t].add(doc.doc_id)

        def polarity(toks: list[str]) -> float:
            return float(sum(1 for t in toks if t in _STANCE_POS) - sum(1 for t in toks if t in _STANCE_NEG))

        pairs: list[ContradictionPair] = []
        for topic, docs_set in sorted(entity_docs.items()):
            docs_sorted = sorted(docs_set)
            if len(docs_sorted) < 2:
                continue
            pol = {d: polarity(tokens_by_doc[d]) for d in docs_sorted}
            for i in range(len(docs_sorted)):
                for j in range(i + 1, len(docs_sorted)):
                    if pol[docs_sorted[i]] * pol[docs_sorted[j]] < 0:
                        pairs.append(
                            ContradictionPair(
                                topic=topic,
                                doc_a=docs_sorted[i],
                                doc_b=docs_sorted[j],
                                polarity_a=pol[docs_sorted[i]],
                                polarity_b=pol[docs_sorted[j]],
                            )
                        )
        return pairs

    def stance_labels(self, docs: list[CorpusDocument]) -> dict[str, str]:
        """Per-document stance: support | neutral | against (lexicon-based)."""
        labels: dict[str, str] = {}
        for doc in docs:
            toks = tokenize(doc.text)
            pos = sum(1 for t in toks if t in _STANCE_POS)
            neg = sum(1 for t in toks if t in _STANCE_NEG)
            labels[doc.doc_id] = CorpusStructuralProfiler._stance(float(pos - neg))
        return labels
