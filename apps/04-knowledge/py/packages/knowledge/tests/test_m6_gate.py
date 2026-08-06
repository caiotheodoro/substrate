"""M6 — grounded gate: classifier states, gate service HTTP, verdict store."""

from fastapi.testclient import TestClient

from substrate_knowledge.core.storage import InMemoryStore
from substrate_knowledge.core.verdicts import RetrievalVerdict, VerdictKind
from substrate_knowledge.m6_gate.gate_api import GroundedGateService, build_gate_app
from substrate_knowledge.m6_gate.verdict_classifier import DeterministicVerdictClassifier
from substrate_knowledge.m6_gate.verdict_store import VerdictStore

SUPPORTIVE = ["Acme reported strong growth and rising profits."]
CONTRADICTORY = ["Acme reported failed results and a sharp decline in profit."]
UNRELATED = ["The weather forecast is sunny."]


def _classifier() -> DeterministicVerdictClassifier:
    return DeterministicVerdictClassifier()


def test_classifier_support():
    verdict = _classifier().classify("Acme profits rose sharply", SUPPORTIVE)
    assert verdict.kind == VerdictKind.SUPPORT
    assert 0.5 < verdict.prob <= 1.0
    assert verdict.citedEvidence is not None


def test_classifier_contradict():
    verdict = _classifier().classify("Acme profits rose sharply", CONTRADICTORY)
    assert verdict.kind == VerdictKind.CONTRADICT
    assert 0.5 < verdict.prob <= 1.0


def test_classifier_silent_on_unrelated_or_empty():
    silent = _classifier().classify("Mars is inhabited", UNRELATED)
    assert silent.kind == VerdictKind.SILENT
    assert silent.citedEvidence is None
    empty = _classifier().classify("Mars is inhabited", [])
    assert empty.kind == VerdictKind.SILENT


def test_classifier_c3_shape():
    verdict = _classifier().classify("Acme profits rose sharply", SUPPORTIVE)
    c3 = verdict.to_c3()
    assert set(c3) == {"kind", "prob", "citedEvidence", "claim"}
    assert c3["kind"] in ("support", "contradict", "silent")
    assert 0.0 <= c3["prob"] <= 1.0
    assert RetrievalVerdict.model_validate(c3) is not None


def test_gate_service_support_and_records():
    service = GroundedGateService(classifier=_classifier(), store=InMemoryStore())
    response = service.gate("Acme profits rose sharply", SUPPORTIVE)
    assert response.blocked is False
    assert response.verdict is not None
    assert response.verdict.kind == VerdictKind.SUPPORT
    assert service.verdict_store.n_verdicts() == 1


def test_gate_service_blocks_empty_subgraph_with_veto():
    service = GroundedGateService(classifier=_classifier(), store=InMemoryStore())
    response = service.gate("Acme profits rose sharply", [])
    assert response.blocked is True
    assert response.verdict is None
    assert "subgraph" in response.reason
    assert len(service.vetoes()) == 1


def test_gate_service_blocks_short_claim():
    service = GroundedGateService(classifier=_classifier(), store=InMemoryStore())
    response = service.gate("x", SUPPORTIVE)
    assert response.blocked is True


def test_gate_http_flow():
    service = GroundedGateService(classifier=_classifier(), store=InMemoryStore())
    app = build_gate_app(service)
    client = TestClient(app)
    support = client.post("/gate", json={"claim": "Acme profits rose sharply", "subgraph": SUPPORTIVE})
    assert support.status_code == 200
    verdict = support.json()["verdict"]
    assert verdict["kind"] == "support"
    assert verdict["prob"] > 0.5
    contradict = client.post("/gate", json={"claim": "Acme profits rose sharply", "subgraph": CONTRADICTORY})
    assert contradict.json()["verdict"]["kind"] == "contradict"
    blocked = client.post("/gate", json={"claim": "Acme profits rose sharply", "subgraph": []})
    assert blocked.json()["blocked"] is True
    vetoes = client.get("/gate/vetoes")
    assert vetoes.status_code == 200
    assert len(vetoes.json()) == 1


def test_verdict_store_support_rate_and_history():
    store = VerdictStore(InMemoryStore())
    classifier = _classifier()
    store.record(classifier.classify("profits rose", ["profits grew"]))
    store.record(classifier.classify("profits declined", ["profits rose"]))
    store.record(classifier.classify("profits declined", ["the weather is sunny today"]), source="query")
    assert store.support_rate() == 1 / 3
    assert store.support_rate("query") == 0.0
    assert store.counts() == {"support": 1, "contradict": 1, "silent": 1}
    history = store.history(claim="profits declined")
    assert len(history) == 2
