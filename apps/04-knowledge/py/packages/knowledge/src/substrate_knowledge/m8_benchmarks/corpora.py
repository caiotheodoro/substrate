"""Synthetic corpora with KNOWN-best retrieval architectures.

These are the measurement substrate for R1 (graph-vs-flat decision rule) and
the characterization suite (A-K-03). Deterministic, no LLM. Each corpus's
`known_best` is asserted by the suite: the rule must agree with measurement.

Design discipline for the benchmark:
  - multi-hop / graph-only corpora are chain-shaped: the answer entity never
    appears in the question, and the gold evidence docs share few or zero
    question terms — a flat index can only reach them through a join;
  - decoy docs match the question lexically but contain no answer entities;
  - each cluster's entities appear only inside that cluster (low cohesion),
    so 2-hop expansion is discriminative instead of covering everything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from substrate_knowledge.core.text import tokenize
from substrate_knowledge.m1_characterization.profiler import _STANCE_NEG, _STANCE_POS, CorpusDocument


@dataclass
class QAItem:
    question: str
    gold_answer: str
    evidence_docs: list[str] = field(default_factory=list)


@dataclass
class SyntheticCorpus:
    name: str
    docs: list[CorpusDocument]
    qa: list[QAItem]
    known_best: str  # vector | vector+graph | graph-only

    def entity_terms(self) -> set[str]:
        counts: dict[str, int] = {}
        for doc in self.docs:
            for t in set(tokenize(doc.text)):
                counts[t] = counts.get(t, 0) + 1
        return {t for t, c in counts.items() if c >= 2}


def _doc(doc_id: str, text: str, source: str = "bench") -> CorpusDocument:
    return CorpusDocument(doc_id=doc_id, text=text, source=source)


def build_multi_hop_corpus() -> SyntheticCorpus:
    """Chain-structured supplier logistics corpus. Every answer requires a
    join across two documents; the answer entity is absent from the query."""
    docs = [
        _doc("mh-01", "Acme's logistics partner is Northwind."),
        _doc("mh-02", "Northwind buys steel from Nordwind."),
        _doc("mh-03", "Nordwind mines ore in the Baltic region."),
        _doc("mh-04", "The Leipzig plant relies on Bergmann."),
        _doc("mh-05", "Bergmann produces bearings with Vega steel."),
        _doc("mh-06", "Vega makes bearings at other sites."),
        _doc("mh-07", "The Lyon site works with Vega."),
        _doc("mh-08", "Vega fabricates chassis frames and axles for Halcyon."),
        _doc("mh-09", "Halcyon ships chassis parts to Europe."),
        _doc("mh-10", "Halcyon ships frames and axles across Europe."),
        _doc("mh-11", "The tablet leader is Halcyon."),
        _doc("mh-12", "Halcyon works with the component maker."),
        _doc("mh-13", "The component maker builds batteries."),
        _doc("mh-14", "Nordwind mines ore and sells it to smelters."),
        _doc("mh-15", "Acme's partner handles ore."),
        _doc("mh-17", "The tablet maker builds batteries."),
    ]
    qa = [
        QAItem("Which firm supplies Acme's logistics partner?", "Nordwind", ["mh-02"]),
        QAItem("Which firm makes the bearings for the Leipzig plant?", "Vega", ["mh-05"]),
        QAItem("Which firm builds the parts that Halcyon ships?", "Vega", ["mh-08"]),
        QAItem("Which firm builds the batteries for the firm that leads the tablet market?", "the component maker", ["mh-12"]),
        QAItem("Which firm buys from the company that mines ore?", "Northwind", ["mh-02"]),
    ]
    return SyntheticCorpus("multi-hop", docs, qa, known_best="vector+graph")


def build_contradiction_corpus() -> SyntheticCorpus:
    """Two camps with opposite stances on a shared topic. Correct evidence is
    stance-filtered; a flat index cannot express stance provenance."""
    docs = [
        _doc("ct-01", "Fusion project partners approved the pilot reactor with strong results and record funding.", source="pro-fusion"),
        _doc("ct-02", "Supporters praised the fusion pilot: the reactor passed tests, costs fell, and funding grew."),
        _doc("ct-03", "The fusion project beat its milestones and won new grants from investors."),
        _doc("ct-04", "Approved fusion tests showed rising performance and a successful pilot."),
        _doc("ct-05", "Critics warn the fusion pilot failed its safety tests, denied funding, and delayed the timeline."),
        _doc("ct-06", "The fusion project lost investor confidence after a failed reactor test."),
        _doc("ct-07", "Opponents cite the fusion project's decline: missed milestones, shrinking grants, and dropped tests."),
        _doc("ct-08", "A warning audit flagged the fusion pilot for defective safety gear and falling performance."),
    ]
    qa = [
        QAItem("Which documents report the fusion project's failed results?", "negative", ["ct-05", "ct-06", "ct-07", "ct-08"]),
        QAItem("Which documents report the fusion project's strong approved results?", "positive", ["ct-01", "ct-02", "ct-03", "ct-04"]),
    ]
    return SyntheticCorpus("contradiction", docs, qa, known_best="vector+graph")


def build_semantic_corpus() -> SyntheticCorpus:
    """Passage-level similarity tasks: the answer lives in the surface text."""
    docs = [
        _doc("sm-01", "Acme Electronics announced a pricing change for its tablet lineup in the third quarter, cutting entry models by fifteen percent."),
        _doc("sm-02", "Halcyon introduced a new laptop with a foldable screen at its spring event, priced above the previous flagship."),
        _doc("sm-03", "The consumer electronics market in Europe grew modestly this year, led by demand for portable audio devices."),
        _doc("sm-04", "Acme's flagship smartphone now ships with a titanium frame and a battery rated for two days of use."),
        _doc("sm-05", "Regulators fined a major phone maker for misleading battery-life advertising last winter."),
        _doc("sm-06", "Industry analysts expect foldable screens to reach mainstream adoption within three years as panel prices fall."),
        _doc("sm-07", "Portable audio revenue rose sharply this year on the strength of wireless earbuds and open-back headphones."),
        _doc("sm-08", "Acme's Q3 pricing change followed a drop in component costs and was met with strong initial demand."),
        _doc("sm-09", "Halcyon's foldable laptop received cautious reviews, with testers praising the display but questioning the hinge."),
        _doc("sm-10", "The phone maker fined last winter has since published corrected battery ratings and pledged transparent labeling."),
    ]
    qa = [
        QAItem("Which document describes Acme's tablet pricing change in the third quarter?", "sm-01", ["sm-01"]),
        QAItem("Which document covers the launch of a foldable-screen laptop?", "sm-02", ["sm-02"]),
        QAItem("Which document discusses growth in portable audio devices?", "sm-03", ["sm-03"]),
        QAItem("Which document reports on the fine against a phone maker?", "sm-05", ["sm-05"]),
        QAItem("Which document explains the reason behind Acme's pricing change?", "sm-08", ["sm-08"]),
    ]
    return SyntheticCorpus("semantic", docs, qa, known_best="vector")


def build_graph_only_corpus() -> SyntheticCorpus:
    """Terse supply-chain facts — pure join queries, no passage semantics.
    The second-tier suppliers (go-11..go-18) exist so the corpus clears the
    characterization minimum (>= MIN_ENTITIES entities) without changing the
    join structure the questions probe."""
    docs = [
        _doc("go-01", "Northwind supplies Acme."),
        _doc("go-02", "Nordwind supplies Northwind."),
        _doc("go-03", "Vega supplies Nordwind."),
        _doc("go-04", "Helios supplies Acme."),
        _doc("go-05", "Vega supplies Helios."),
        _doc("go-06", "Bergmann supplies Acme."),
        _doc("go-07", "Nordwind supplies Bergmann."),
        _doc("go-08", "Halcyon supplies Vega."),
        _doc("go-09", "Bergmann supplies Halcyon."),
        _doc("go-10", "Halcyon supplies Nordwind."),
        _doc("go-11", "Zephyr supplies Nordwind."),
        _doc("go-12", "Zephyr supplies Vega."),
        _doc("go-13", "Icarus supplies Helios."),
        _doc("go-14", "Icarus supplies Bergmann."),
        _doc("go-15", "Astra supplies Northwind."),
        _doc("go-16", "Astra supplies Halcyon."),
        _doc("go-17", "Orion supplies Helios."),
        _doc("go-18", "Orion supplies Halcyon."),
    ]
    qa = [
        QAItem("Which firm supplies Acme's supplier?", "Nordwind and Vega", ["go-02", "go-05"]),
        QAItem("Which firm supplies the company that supplies Helios?", "Nordwind and Halcyon", ["go-03", "go-08"]),
        QAItem("Which firm supplies the company that supplies Bergmann?", "Vega and Halcyon", ["go-03", "go-10"]),
        QAItem("Which firm supplies the company that supplies Halcyon?", "Nordwind", ["go-03", "go-07"]),
    ]
    return SyntheticCorpus("graph-only", docs, qa, known_best="graph-only")


def build_all_corpora() -> list[SyntheticCorpus]:
    return [
        build_multi_hop_corpus(),
        build_contradiction_corpus(),
        build_semantic_corpus(),
        build_graph_only_corpus(),
    ]


def query_polarity(question: str) -> str:
    """Polarity probe for stance-aware retrieval (contradiction corpus)."""
    toks = set(tokenize(question))
    pos = toks & _STANCE_POS
    neg = toks & _STANCE_NEG
    if pos and not neg:
        return "support"
    if neg and not pos:
        return "against"
    return "neutral"
