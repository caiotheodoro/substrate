"""M3 — entity resolution: blocking, Fellegi-Sunter, calibration, queue."""

import math

from fastapi.testclient import TestClient

from substrate_knowledge.core.storage import InMemoryStore
from substrate_knowledge.m3_resolution.blocker import Blocker, EntityRecord, canonical_name
from substrate_knowledge.m3_resolution.calibrator import ResolutionCalibrator
from substrate_knowledge.m3_resolution.canonical_store import CanonicalizationStore
from substrate_knowledge.m3_resolution.human_queue import HumanConfirmationQueue
from substrate_knowledge.m3_resolution.queue_api import build_app
from substrate_knowledge.m3_resolution.similarity import COMPARATORS, DEFAULT_M_PROBS, DEFAULT_U_PROBS, FelgiSunterScorer


def _rec(entity_id: str, name: str, type_: str = "Organization", source: str = "doc", date: str | None = None) -> EntityRecord:
    return EntityRecord(entity_id=entity_id, name=name, type=type_, source=source, date=date)


def test_canonical_name_normalization():
    assert canonical_name("Acme Corp.") == canonical_name("acme  corp")
    assert canonical_name("Vega Assemblies") == "vegaassemblies"


def test_blocker_groups_on_name_and_type():
    records = [
        _rec("e1", "Acme Corp", source="d1"),
        _rec("e2", "Acme Corp", source="d2"),
        _rec("e3", "Northwind", source="d3"),
        _rec("e4", "Laura Berg", "Person", source="d4"),
        _rec("e5", "Laura Berg", "Person", source="d5"),
    ]
    blocks = Blocker().block(records)
    by_key = {(b.key_type, b.key): {m.entity_id for m in b.members} for b in blocks}
    assert ("name", "acmecorp") in by_key
    assert by_key[("name", "acmecorp")] == {"e1", "e2"}
    assert ("type", "organization") in by_key
    assert ("type", "person") in by_key
    assert ("name", "lauraberg") in by_key


def test_fellegi_sunter_log_linearity():
    scorer = FelgiSunterScorer()
    agree = scorer.agreement_weight((True, True, True, True))
    disagree = scorer.agreement_weight((False, False, False, False))
    assert agree > disagree
    # Flipping one comparator changes the total weight by exactly the
    # comparator's log-odds difference (the additive property of FS).
    for i in range(len(COMPARATORS)):
        base = [False] * len(COMPARATORS)
        base[i] = True
        flipped = tuple(base)
        base[i] = False
        unchanged = tuple(base)
        m, u = DEFAULT_M_PROBS[i], DEFAULT_U_PROBS[i]
        delta = math.log(m / u) - math.log((1.0 - m) / (1.0 - u))
        assert math.isclose(scorer.agreement_weight(flipped) - scorer.agreement_weight(unchanged), delta)


def test_fellegi_sunter_manual_weight_matches():
    scorer = FelgiSunterScorer()
    expected = sum(
        math.log(m / u) if agree else math.log((1 - m) / (1 - u))
        for agree, m, u in zip((True, True, False, False), DEFAULT_M_PROBS, DEFAULT_U_PROBS)
    )
    assert math.isclose(scorer.agreement_weight((True, True, False, False)), expected)


def test_similarity_scores_matches_above_non_matches():
    scorer = FelgiSunterScorer()
    match = _rec("e1", "Acme Corp", source="d1")
    dup = _rec("e2", "Acme Corp", source="d2")
    other = _rec("e3", "Northwind", source="d3")
    pair_match = scorer.score_pair(match, dup)
    pair_other = scorer.score_pair(match, other)
    assert pair_match.fused_score > pair_other.fused_score
    assert pair_match.comparisons["name"] is True
    assert pair_other.comparisons["name"] is False


def test_calibrator_finds_queue_threshold():
    scorer = FelgiSunterScorer()
    records = [_rec(f"e{i}", "Acme Corp" if i % 2 == 0 else "Northwind", source=f"d{i % 3}") for i in range(12)]
    pairs = []
    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            is_match = canonical_name(records[i].name) == canonical_name(records[j].name)
            pairs.append((scorer.score_pair(records[i], records[j]), is_match))
    calibration = ResolutionCalibrator().calibrate(pairs)
    assert calibration.queue_threshold is not None
    top_band = calibration.bands[0]
    assert top_band.precision == 1.0


def test_canonicalization_store_aliases_and_audit():
    store = CanonicalizationStore(InMemoryStore())
    cid = store.create_canonical(_rec("e1", "Acme Corp", source="d1"))
    store.merge(cid, "Acme Corporation", _rec("e2", "Acme Corporation", source="d2"))
    assert store.resolve_alias("acme corp") == cid
    assert store.resolve_alias("Acme Corporation") == cid
    assert "acmecorporation" in store.aliases(cid)
    assert "d2" in store.source_refs(cid)
    assert len(store.audit()) == 2


def test_human_queue_resolve_and_audit():
    store = InMemoryStore()
    queue = HumanConfirmationQueue(store)
    item = queue.enqueue({"name": "Acme Corp"}, {"name": "Acme Corporation"}, 8.2)
    assert queue.queue_depth() == 1
    resolved = queue.resolve(item.id, "merge", audited_by="tester")
    assert resolved.status == "resolved"
    assert resolved.resolution == "merge"
    assert queue.queue_depth() == 0
    assert len(queue.audit_log()) == 1


def test_human_queue_api_flow():
    queue = HumanConfirmationQueue(InMemoryStore())
    queue.enqueue({"name": "Acme Corp"}, {"name": "Acme Corporation"}, 7.9)
    app = build_app(queue)
    client = TestClient(app)
    pending = client.get("/queue")
    assert pending.status_code == 200
    assert len(pending.json()) == 1
    item_id = pending.json()[0]["id"]
    page = client.get("/")
    assert "Acme Corp" in page.text
    resolved = client.post(f"/resolve/{item_id}", json={"resolution": "merge", "audited_by": "test"})
    assert resolved.json()["status"] == "resolved"
    assert len(client.get("/audit").json()) == 1
