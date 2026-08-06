"""M7 — observability: graph health monitor, metrics exporter."""

from substrate_knowledge.m4_graph.graph_store import InMemoryGraph
from substrate_knowledge.m7_observability.health import GraphHealthMonitor
from substrate_knowledge.m7_observability.metrics import NoopMetricsExporter, get_exporter


def _graph_with_clusters() -> InMemoryGraph:
    graph = InMemoryGraph()
    for node_id in ("n1", "n2", "n3", "n4", "n5", "n6"):
        graph.upsert_node(node_id, "Organization", node_id)
    for a, b in (("n1", "n2"), ("n2", "n3"), ("n1", "n3")):
        graph.upsert_edge("provides", a, b, source_doc="d1")
    for a, b in (("n4", "n5"), ("n5", "n6")):
        graph.upsert_edge("provides", a, b, source_doc="d2")
    return graph


def test_graph_health_components_and_coverage():
    graph = _graph_with_clusters()
    provenance = [
        ("n1", "d1"), ("n2", "d1"), ("n3", "d1"),
        ("n4", "d2"), ("n5", "d2"), ("n6", "d2"),
    ]
    report = GraphHealthMonitor().report(graph, provenance)
    assert report.n_nodes == 6
    assert report.entity_coverage == {"d1": 3, "d2": 3}
    assert report.n_sources == 2
    assert report.relation_density > 0.0
    assert report.giant_component_fraction == 0.5
    assert report.n_components == 2
    assert report.n_orphans == 0
    assert report.connectivity == 2 / 6


def test_graph_health_orphan_detection():
    graph = _graph_with_clusters()
    graph.upsert_node("loner", "Organization", "Loner")
    report = GraphHealthMonitor().report(graph)
    assert report.n_orphans == 1
    assert report.orphan_fraction > 0.0


def test_metrics_exporter_noop_default():
    exporter = get_exporter()
    assert isinstance(exporter, NoopMetricsExporter)
    exporter.gauge("knowledge_gate_support_rate", 0.5)
    exporter.counter_inc("knowledge_gate_verdicts")
    assert exporter.snapshot() == {}
