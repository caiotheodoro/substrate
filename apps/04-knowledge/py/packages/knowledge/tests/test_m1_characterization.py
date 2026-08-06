"""M1 — task characterization: profiler, decision rule, probes, suite."""

from substrate_knowledge.m1_characterization.decision import DecisionRule, VECTOR, VECTOR_GRAPH
from substrate_knowledge.m1_characterization.profiler import (
    CorpusDocument,
    CorpusStructuralProfiler,
)
from substrate_knowledge.m1_characterization.probes import PropertyProbes
from substrate_knowledge.m1_characterization.suite import CharacterizationSuite
from substrate_knowledge.m8_benchmarks.corpora import build_all_corpora


def _docs(pairs: list[tuple[str, str]]) -> list[CorpusDocument]:
    return [CorpusDocument(doc_id=d, text=t) for d, t in pairs]


def test_multi_hop_index_detects_two_hop_chain():
    # A--doc1--B, B--doc2--C: C is reachable from A only in exactly 2 hops.
    docs = _docs(
        [
            ("d1", "Acme partners with Northwind."),
            ("d2", "Northwind buys from Nordwind."),
            ("d3", "Acme sells ore to other buyers."),
            ("d4", "Nordwind ships ore to the region."),
        ]
    )
    profile = CorpusStructuralProfiler().profile(docs)
    assert profile.multi_hop_index > 0.0
    assert profile.n_entities >= 3


def test_profiler_indices_on_crafted_corpus():
    docs = _docs(
        [
            ("d1", "Acme partners with Northwind."),
            ("d2", "Northwind buys from Nordwind."),
            ("d3", "Nordwind mines ore in the Baltic region."),
            ("d4", "Acme's rival approves the strong plan."),
            ("d5", "The rival fails and declines."),
            ("d6", "Acme's plan is approved by the rival."),
        ]
    )
    profile = CorpusStructuralProfiler().profile(docs)
    assert profile.multi_hop_index >= 0.0
    assert 0.0 <= profile.contradiction_index <= 1.0
    stance = profile.stance_distribution
    assert set(stance) == {"support", "neutral", "against"}
    assert abs(sum(stance.values()) - 1.0) < 1e-6
    assert 0.0 <= profile.aggregation_share <= 1.0


def test_decision_rule_on_all_corpora():
    rule = DecisionRule()
    for corpus in build_all_corpora():
        profile = CorpusStructuralProfiler().profile(corpus.docs)
        verdict = rule.decide(profile)
        assert verdict.refusal is None, f"{corpus.name} should not be refused: {verdict.refusal}"
        assert verdict.architecture in ("vector", "vector+graph", "graph-only")
        assert 0.0 <= verdict.confidence <= 1.0


def test_decision_rule_refuses_tiny_corpus():
    docs = _docs([("d1", "Acme."), ("d2", "Northwind.")])
    verdict = DecisionRule().decide(CorpusStructuralProfiler().profile(docs))
    assert verdict.refusal is not None
    assert verdict.architecture == VECTOR


def test_decision_rule_vectors_agree_with_known_best():
    suite = CharacterizationSuite()
    report = suite.run()
    assert report.agreement_rate() >= 0.75
    for result in report.results:
        assert result.rule_verdict.get("architecture") in (VECTOR, VECTOR_GRAPH, "graph-only")
        assert result.measured_winner in (VECTOR, VECTOR_GRAPH, "graph-only", "tie")


def test_probes_find_contradiction_pairs():
    docs = _docs(
        [
            ("d1", "Fusion project approved with strong results and record growth."),
            ("d2", "Fusion project failed, declined, and lost funding."),
            ("d3", "Fusion project approved new grants and beat milestones."),
        ]
    )
    probes = PropertyProbes()
    pairs = probes.contradiction_pairs(docs)
    assert any(p.topic == "fusion" for p in pairs)
    assert any(p.polarity_a * p.polarity_b < 0 for p in pairs)
    labels = probes.stance_labels(docs)
    assert set(labels) == {"d1", "d2", "d3"}
    assert labels["d2"] == "against"
    assert labels["d1"] == "support"


def test_probes_multi_hop_reachability():
    docs = _docs(
        [
            ("d1", "Acme partners with Northwind."),
            ("d2", "Northwind buys from Nordwind."),
            ("d3", "Acme sells ore to other buyers."),
            ("d4", "Nordwind ships ore to the region."),
        ]
    )
    probes = PropertyProbes()
    reach = probes.multi_hop_reachability(docs, max_hops=2)
    assert reach > 0.0


def test_characterization_api_refuses_small_and_records_vectors():
    from fastapi.testclient import TestClient

    from substrate_knowledge.m1_characterization.api import build_characterize_app

    client = TestClient(build_characterize_app())
    tiny = client.post("/characterize", json={"docs": [{"doc_id": "a", "text": "Acme."}]})
    assert tiny.status_code == 200
    assert tiny.json()["verdict"]["refusal"] is not None

    corpus = [c for c in build_all_corpora() if c.name == "semantic"][0]
    payload = {"docs": [{"doc_id": d.doc_id, "text": d.text, "source": d.source} for d in corpus.docs]}
    verdict = client.post("/characterize", json=payload).json()["verdict"]
    assert verdict["architecture"] == VECTOR
    assert verdict["refusal"] is None
