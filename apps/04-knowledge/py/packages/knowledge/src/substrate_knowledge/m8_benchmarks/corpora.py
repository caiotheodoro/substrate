"""Synthetic corpora with KNOWN-best retrieval architectures.

These are the measurement substrate for R1 (graph-vs-flat decision rule) and
the characterization suite (A-K-03). Deterministic, no LLM. Each corpus's
`known_best` is asserted by the suite: the rule must agree with measurement.
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
    """Chain-structured supplier logistics corpus. Answers require joining
    two documents (the answer entity never appears in the question)."""
    docs = [
        _doc("mh-01", "Acme Corporation distributes its consumer electronics across Europe through network logistics partners."),
        _doc("mh-02", "Northwind Logistics provides freight services for Acme's European warehouses and retail depots."),
        _doc("mh-03", "Nordwind's fleet of cargo vessels connects the Baltic ports where Acme warehouses are located."),
        _doc("mh-04", "Helios Cargo moves Acme's shipments between France and Germany under a long-term contract."),
        _doc("mh-05", "Acme manufactures devices at plants in Lyon and Leipzig supplied by regional parts vendors."),
        _doc("mh-06", "Bergmann Components supplies bearings to the Acme plant in Leipzig."),
        _doc("mh-07", "Vega Assemblies fabricates chassis frames for the Acme plant in Lyon."),
        _doc("mh-08", "Bergmann Components also serves the Leipzig plant of Halcyon Electronics, a rival of Acme."),
        _doc("mh-09", "Halcyon Electronics ships finished tablets from Leipzig through Nordwind Logistics."),
        _doc("mh-10", "Acme's retail depots in Berlin and Warsaw receive inventory twice weekly from Northwind Logistics."),
    ]
    qa = [
        QAItem(
            "Which logistics firm handles Acme's distribution across Europe?",
            "Northwind Logistics",
            ["mh-02"],
        ),
        QAItem(
            "Which company provides bearings to Acme's plant in Leipzig?",
            "Bergmann Components",
            ["mh-06"],
        ),
        QAItem(
            "Who fabricates chassis frames for Acme's Lyon plant?",
            "Vega Assemblies",
            ["mh-07"],
        ),
        QAItem(
            "Which carrier moves Acme shipments between France and Germany?",
            "Helios Cargo",
            ["mh-04"],
        ),
        QAItem(
            "Which rival of Acme ships tablets through Nordwind Logistics?",
            "Halcyon Electronics",
            ["mh-09"],
        ),
        QAItem(
            "Which vendor supplies parts to Acme's Leipzig plant?",
            "Bergmann Components",
            ["mh-06"],
        ),
    ]
    return SyntheticCorpus("multi-hop", docs, qa, known_best="vector+graph")


def build_contradiction_corpus() -> SyntheticCorpus:
    """Two camps with opposite stances on a shared topic. Correct evidence is
    stance-filtered; a flat index cannot express stance provenance."""
    docs = [
        _doc("ct-01", "The fusion pilot program launched this year with approved funding and record investment from industry partners.", source="pro-fusion"),
        _doc("ct-02", "Supporters of the fusion program cite strong results: the reactor design was validated, testing grew, and costs declined steadily."),
        _doc("ct-03", "The fusion roadmap gained momentum after the government approved new grants and the program beat its milestones."),
        _doc("ct-04", "A major investor committed new capital to fusion development, calling the engineering progress remarkable and the outlook positive."),
        _doc("ct-05", "Critics warn the fusion program faces regulatory hurdles, cost overruns, and repeated delays that deny its promised timeline."),
        _doc("ct-06", "Opponents of the fusion project point to a failed reactor test, disputed safety claims, and a sharp drop in public confidence."),
        _doc("ct-07", "An audit flagged the fusion program for controversial spending, layoffs among suppliers, and shrinking output projections."),
        _doc("ct-08", "The fusion reactor controversy deepened after investigators found defects in the cooling loop and the project missed its deadline."),
        _doc("ct-09", "Regulators approved the fusion site permit, a win for backers who argued the technology is ready for deployment."),
        _doc("ct-10", "The fusion project suffered a loss when its main contractor withdrew, leaving funding gaps and idle plants behind."),
    ]
    qa = [
        QAItem("Which documents take a negative stance on the fusion program?", "ct-05, ct-06, ct-07, ct-08, ct-10", ["ct-05", "ct-06", "ct-07", "ct-08", "ct-10"]),
        QAItem("Which documents support the fusion program?", "ct-01, ct-02, ct-03, ct-04, ct-09", ["ct-01", "ct-02", "ct-03", "ct-04", "ct-09"]),
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
    """Terse relation statements — pure join queries, no passage semantics."""
    docs = [
        _doc("go-01", "Northwind supplies paper to Acme."),
        _doc("go-02", "Northwind supplies ink to Halcyon."),
        _doc("go-03", "Acme buys glass from Vega."),
        _doc("go-04", "Halcyon buys glass from Vega."),
        _doc("go-05", "Acme buys chips from Bergmann."),
        _doc("go-06", "Halcyon buys chips from Bergmann."),
        _doc("go-07", "Vega buys resin from Nordwind."),
        _doc("go-08", "Bergmann buys steel from Nordwind."),
        _doc("go-09", "Nordwind supplies wire to Vega."),
        _doc("go-10", "Nordwind supplies tin to Bergmann."),
    ]
    qa = [
        QAItem("What does Northwind supply to Acme?", "paper", ["go-01"]),
        QAItem("Who supplies glass to Halcyon?", "Vega", ["go-04"]),
        QAItem("What does Vega buy from Nordwind?", "resin", ["go-07"]),
        QAItem("Who does Bergmann buy steel from?", "Nordwind", ["go-08"]),
        QAItem("What does Nordwind supply to Bergmann?", "tin", ["go-10"]),
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
