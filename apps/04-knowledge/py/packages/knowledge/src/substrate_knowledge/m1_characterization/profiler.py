"""A-K-01 corpus-structural-profiler.

Measures the structural properties that decide whether graph-backed retrieval
pays for itself (SPEC R1): multi-hop reachability, contradiction structure,
stance distribution, and aggregation share. Every metric is deterministic and
documented — no LLM in the loop.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from substrate_knowledge.core.text import tokenize

_STANCE_POS = frozenset(
    """launch acquire acquired growth grew profit profitable approved win beat exceeded record
    strong adopt adopted invest partnership partner expand expanded rise rising rose surge surplus
    innovative leader award gained increase doubled tripled""".split()
)
_STANCE_NEG = frozenset(
    """fail failed loss decline declined declining layoff layoffs recall recalled violate violated
    ban banned defect lawsuit litigation shrink dropped controversy denies deny loss loses
    shortage warning fine fined penalty censure investigated investigation""".split()
)
_AGG_PATTERN = re.compile(r"\b(total|all|every|count|sum|how many|aggregate|combined|per)\b", re.I)

MIN_ENTITY_FREQ = 2
MIN_SHARED_TOPIC_DOCS = 2
SAMPLE_ENTITIES = 80


@dataclass
class CorpusDocument:
    doc_id: str
    text: str
    source: str = "unknown"
    ts: str | None = None


@dataclass
class CorpusProfile:
    n_docs: int
    n_entities: int
    multi_hop_index: float = 0.0
    avg_shortest_path: float = 0.0
    contradiction_index: float = 0.0
    stance_distribution: dict[str, float] = field(default_factory=lambda: {"support": 0.0, "neutral": 0.0, "against": 0.0})
    aggregation_share: float = 0.0
    cohesion: float = 0.0

    def to_dict(self) -> dict:
        return {
            "n_docs": self.n_docs,
            "n_entities": self.n_entities,
            "multi_hop_index": round(self.multi_hop_index, 4),
            "avg_shortest_path": round(self.avg_shortest_path, 4),
            "contradiction_index": round(self.contradiction_index, 4),
            "stance_distribution": {k: round(v, 4) for k, v in self.stance_distribution.items()},
            "aggregation_share": round(self.aggregation_share, 4),
            "cohesion": round(self.cohesion, 4),
        }


class CorpusStructuralProfiler:
    """All metrics are pure functions of (documents); caching by content hash."""

    def profile(self, docs: list[CorpusDocument]) -> CorpusProfile:
        if not docs:
            return CorpusProfile(n_docs=0, n_entities=0)
        tokens_by_doc = {d.doc_id: tokenize(d.text) for d in docs}
        doc_freq = Counter(t for tokens in tokens_by_doc.values() for t in set(tokens))

        entities = sorted(t for t, f in doc_freq.items() if f >= MIN_ENTITY_FREQ)
        entity_docs: dict[str, set[str]] = defaultdict(set)
        for doc in docs:
            seen = set(tokens_by_doc[doc.doc_id])
            for t in seen:
                if doc_freq[t] >= MIN_ENTITY_FREQ:
                    entity_docs[t].add(doc.doc_id)

        adjacency: dict[str, set[str]] = {e: set() for e in entities}
        for doc in docs:
            doc_entities = [e for e in entities if e in tokens_by_doc[doc.doc_id]]
            for i, a in enumerate(doc_entities):
                for b in doc_entities[i + 1 :]:
                    adjacency[a].add(b)
                    adjacency[b].add(a)

        mh, asp = self._reachability(entities, adjacency)
        ci, stance_hist = self._contradiction(entities, entity_docs, tokens_by_doc)
        agg = sum(1 for d in docs if _AGG_PATTERN.search(d.text)) / len(docs)
        cohesion = self._giant_component_fraction(entities, adjacency)

        return CorpusProfile(
            n_docs=len(docs),
            n_entities=len(entities),
            multi_hop_index=mh,
            avg_shortest_path=asp,
            contradiction_index=ci,
            stance_distribution=stance_hist,
            aggregation_share=agg,
            cohesion=cohesion,
        )

    # ------------------------------------------------------------------
    def _reachability(self, entities: list[str], adjacency: dict[str, set[str]]) -> tuple[float, float]:
        if len(entities) < 2:
            return 0.0, 0.0
        sample = entities[:SAMPLE_ENTITIES]
        two_hop_pairs = 0
        total_pairs = 0
        path_lengths: list[float] = []
        for u in sample:
            dist = self._bfs(u, adjacency, max_depth=3)
            for v in entities:
                if v == u or v not in sample:
                    continue
                total_pairs += 1
                d = dist.get(v)
                if d == 2:
                    two_hop_pairs += 1
                if d and d >= 1:
                    path_lengths.append(float(d))
        mh = two_hop_pairs / total_pairs if total_pairs else 0.0
        asp = sum(path_lengths) / len(path_lengths) if path_lengths else 0.0
        return mh, asp

    @staticmethod
    def _bfs(start: str, adjacency: dict[str, set[str]], max_depth: int) -> dict[str, int]:
        dist = {start: 0}
        frontier = [start]
        depth = 0
        while frontier and depth < max_depth:
            depth += 1
            nxt: list[str] = []
            for node in frontier:
                for nb in adjacency.get(node, ()):
                    if nb not in dist:
                        dist[nb] = depth
                        nxt.append(nb)
            frontier = nxt
        return dist

    @staticmethod
    def _contradiction(
        entities: list[str],
        entity_docs: dict[str, set[str]],
        tokens_by_doc: dict[str, list[str]],
    ) -> tuple[float, dict[str, float]]:
        shared_pairs = 0
        contradiction_pairs = 0
        stance_hist: Counter[str] = Counter()
        for e in entities:
            docs = sorted(d for d in entity_docs[e] if len(entity_docs[e]) >= MIN_SHARED_TOPIC_DOCS)
            if len(docs) < 2:
                continue
            polarity: dict[str, float] = {}
            for doc in docs:
                toks = tokens_by_doc[doc]
                pos = sum(1 for t in toks if t in _STANCE_POS)
                neg = sum(1 for t in toks if t in _STANCE_NEG)
                pol = float(pos - neg)
                polarity[doc] = pol
                stance_hist[CorpusStructuralProfiler._stance(pol)] += 1
            for i in range(len(docs)):
                for j in range(i + 1, len(docs)):
                    shared_pairs += 1
                    if polarity[docs[i]] * polarity[docs[j]] < 0:
                        contradiction_pairs += 1
        ci = contradiction_pairs / shared_pairs if shared_pairs else 0.0
        total = sum(stance_hist.values())
        norm = {k: stance_hist[k] / total for k in ("support", "neutral", "against")} if total else {
            "support": 0.0,
            "neutral": 0.0,
            "against": 0.0,
        }
        return ci, norm

    @staticmethod
    def _stance(polarity: float) -> str:
        if polarity > 0:
            return "support"
        if polarity < 0:
            return "against"
        return "neutral"

    @staticmethod
    def _giant_component_fraction(entities: list[str], adjacency: dict[str, set[str]]) -> float:
        if not entities:
            return 0.0
        seen: set[str] = set()
        components: list[int] = []
        for e in entities:
            if e in seen:
                continue
            stack = [e]
            seen.add(e)
            size = 0
            while stack:
                node = stack.pop()
                size += 1
                for nb in adjacency.get(node, ()):
                    if nb not in seen:
                        seen.add(nb)
                        stack.append(nb)
            components.append(size)
        return max(components) / len(entities) if components else 0.0
