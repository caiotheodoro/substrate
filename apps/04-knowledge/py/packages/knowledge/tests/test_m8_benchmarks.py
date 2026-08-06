"""M8 — benchmarks: R1 graph-vs-flat dominance, R2 error propagation, R5 QA."""

from substrate_knowledge.m8_benchmarks.corpora import build_all_corpora, build_multi_hop_corpus, build_semantic_corpus
from substrate_knowledge.m8_benchmarks.error_propagation import ErrorPropagationRunner
from substrate_knowledge.m8_benchmarks.graph_vs_flat import GraphVsFlatRunner
from substrate_knowledge.m8_benchmarks.retrieval_qa import RetrievalQARunner, context_precision, faithfulness


def test_graph_beats_flat_on_multi_hop_corpus():
    corpus = build_multi_hop_corpus()
    result = GraphVsFlatRunner().run(corpus)
    assert result.graph.evidence_recall > result.flat.evidence_recall
    assert result.graph.evidence_recall == 1.0
    assert result.flat.evidence_recall == 0.0


def test_graph_beats_flat_on_contradiction_corpus():
    corpus = [c for c in build_all_corpora() if c.name == "contradiction"][0]
    result = GraphVsFlatRunner().run(corpus)
    assert result.graph.evidence_recall > result.flat.evidence_recall
    assert result.graph.evidence_recall == 1.0


def test_graph_beats_flat_on_graph_only_corpus():
    corpus = [c for c in build_all_corpora() if c.name == "graph-only"][0]
    result = GraphVsFlatRunner().run(corpus)
    assert result.graph.evidence_recall > result.flat.evidence_recall
    assert result.graph.evidence_recall == 1.0


def test_flat_beats_graph_on_semantic_corpus():
    corpus = build_semantic_corpus()
    result = GraphVsFlatRunner().run(corpus)
    assert result.flat.evidence_recall > result.graph.evidence_recall
    assert result.flat.evidence_recall == 1.0


def test_runner_result_shape():
    result = GraphVsFlatRunner().run(build_multi_hop_corpus())
    payload = result.to_dict()
    assert set(payload) == {"corpus", "budget", "measured_winner", "flat", "graph", "hybrid"}
    for mode in ("flat", "graph", "hybrid"):
        assert 0.0 <= payload[mode]["evidence_recall"] <= 1.0


def test_error_propagation_curve_monotone_and_zero_point_perfect():
    runner = ErrorPropagationRunner(seed=11, n_queries_per_rate=300)
    curve = runner.run((0.0, 0.2, 0.4, 0.6))
    rates = [point.error_rate for point in curve]
    assert rates == [0.0, 0.2, 0.4, 0.6]
    assert curve[0].correct_resolution == 1.0
    resolutions = [point.correct_resolution for point in curve]
    assert all(b <= a for a, b in zip(resolutions, resolutions[1:]))
    assert curve[-1].correct_resolution < curve[0].correct_resolution


def test_error_propagation_crosses_negative_threshold():
    runner = ErrorPropagationRunner(seed=3, n_queries_per_rate=400)
    curve = runner.run((0.0, 0.3, 0.5))
    assert curve[0].correct_resolution == 1.0
    assert curve[-1].correct_resolution < 0.25


def test_faithfulness_and_context_precision_metrics_in_range():
    assert faithfulness(["Northwind supplies Acme"], ["Northwind supplies Acme and Halcyon."]) == 1.0
    assert faithfulness(["Northwind supplies Acme"], ["Vega sells devices to Helios."]) == 0.0
    assert 0.0 <= context_precision(["d1", "d2", "d3"], {"d2"}) <= 1.0
    assert context_precision(["d1", "d2", "d3"], {"d2"}) == (1 / 2) / 1
    assert context_precision(["d1", "d2"], {"d3"}) == 0.0


def test_retrieval_qa_suite_scores_in_range():
    runner = RetrievalQARunner()
    report = runner.run(build_multi_hop_corpus(), mode="graph")
    assert report.answer_accuracy == 1.0
    assert 0.0 <= report.mean_faithfulness <= 1.0
    assert 0.0 <= report.mean_context_precision <= 1.0
    assert report.mean_faithfulness > 0.5
    assert report.mean_context_precision > 0.5
