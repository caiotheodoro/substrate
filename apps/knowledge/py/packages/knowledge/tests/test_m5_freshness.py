"""M5 — freshness: PSI drift, change detection, ledger, scheduler."""

import time

import numpy as np

from substrate_knowledge.core.storage import InMemoryStore
from substrate_knowledge.m5_freshness.change_detector import Source, SourceChangeDetector
from substrate_knowledge.m5_freshness.drift import DriftMonitor, psi
from substrate_knowledge.m5_freshness.ledger import FreshnessLedger
from substrate_knowledge.m5_freshness.scheduler import ReingestionScheduler
from substrate_knowledge.m9_platform.bus import InMemoryBus


def test_psi_identical_distributions_zero():
    rng = np.random.RandomState(0)
    a = rng.normal(0, 1, 1000)
    assert psi(a, a) == 0.0
    assert psi(a, rng.normal(0, 1, 1000)) < 0.05


def test_psi_shifted_distribution_detects_drift():
    rng = np.random.RandomState(0)
    a = rng.normal(0, 1, 1000)
    b = rng.normal(4, 1, 1000)
    assert psi(a, b) > 1.0
    report = DriftMonitor().monitor({"score": a}, {"score": b})
    assert report.verdict == "drift"
    assert report.feature_psi["score"] > 1.0


def test_drift_monitor_ok_on_matching_distributions():
    rng = np.random.RandomState(7)
    a = rng.normal(0, 1, 1000)
    b = rng.normal(0, 1, 1000)
    report = DriftMonitor().monitor({"score": a}, {"score": b})
    assert report.verdict == "ok"


def test_drift_monitor_embedding_drift():
    from substrate_knowledge.core.text import hash_embed

    source_embeddings = [hash_embed("acme logistics partners") for _ in range(8)]
    graph_embeddings = [hash_embed("northwind freight shipping") for _ in range(8)]
    report = DriftMonitor().monitor({}, {}, source_embeddings, graph_embeddings)
    assert report.embedding_drift > 0.0


def test_freshness_ledger_staleness():
    store = InMemoryStore()
    ledger = FreshnessLedger(store)
    assert ledger.staleness_age("s1") is None
    now = time.time()
    ledger.record_ingestion("s1", ts=now - 3600, cost=5.0, doc_count=10)
    assert ledger.last_ingested("s1") == now - 3600
    assert ledger.staleness_age("s1", now=now) == 3600.0
    assert ledger.is_stale("s1", max_age_s=600, now=now) is True
    assert ledger.is_stale("s1", max_age_s=7200, now=now) is False
    assert ledger.cost_total("s1") == 5.0
    ledger.record_ingestion("s1", ts=now, cost=3.0)
    assert ledger.cost_total("s1") == 8.0
    assert ledger.sources() == ["s1"]


def test_source_change_detector_content_hash_polling(tmp_path):
    store = InMemoryStore()
    ledger = FreshnessLedger(store)
    bus = InMemoryBus()
    detector = SourceChangeDetector(ledger=ledger, bus=bus)
    path = tmp_path / "doc.txt"
    path.write_text("version one", encoding="utf-8")
    source = Source(id="s1", name="doc", path=str(path))
    assert len(detector.poll([source])) == 1
    assert len(bus.history("source.changed")) == 1
    assert len(detector.poll([source])) == 0
    path.write_text("version two", encoding="utf-8")
    changes = detector.poll([source])
    assert len(changes) == 1
    assert changes[0].old_hash != changes[0].new_hash


def test_reingestion_scheduler_trigger():
    store = InMemoryStore()
    ledger = FreshnessLedger(store)
    bus = InMemoryBus()
    scheduler = ReingestionScheduler(ledger, bus=bus)
    key = scheduler.trigger("s1", reason="drift")
    assert key.startswith("trigger:s1:")
    assert len(ledger.trigger_history("s1")) == 1
    assert len(bus.history("source.changed")) == 1
    scheduler.shutdown()
