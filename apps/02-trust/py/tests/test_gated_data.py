"""M4 gated data pipeline: seeds → gates → Dataset with provenance (A-T-28),
verifiability (A-T-23), label quality (A-T-24), contamination (A-T-25),
diversity (A-T-26), ingest + provenance (A-T-22/27)."""
import pytest

from trust.gated_data.contamination import ContaminationGate, InMemoryQuarantineStore, ngram_overlap
from trust.gated_data.diversity import DiversityGate, StubEmbedder, cluster_vectors
from trust.gated_data.ingest import StaticWorldSeedSource, stamp_provenance
from trust.gated_data.label_quality import AutoReviewer, LabelQualityGate
from trust.gated_data.models import GatePolicy, SeedRecord
from trust.gated_data.pipeline import gate
from trust.gated_data.provenance import InMemoryProvenanceTracker
from trust.gated_data.verifiability import VerifiabilityGate, assess_verifiability

HOLDOUT = ["The capital of the federation is Veria, and the currency is the mark."]


def _seed(sample_id, content, label=True, signal_kinds=("tool",), metadata=None):
    return SeedRecord(
        sample_id=sample_id,
        content=content,
        label=label,
        source="test",
        world="w1",
        signal_kinds=list(signal_kinds),
        metadata=metadata or {},
    )


def _default_seeds():
    return [
        _seed("s-ok", "The reactor output is 3.8 gigawatts, within limits.", True, ["tool"], {"tool_error": False, "tool_result_sign": "positive"}),
        _seed("s-unverifiable", "A claim with no evidence channel at all.", True, [], {}),
        _seed("s-contradicted", "The reactor is failing.", False, ["retrieval"], {"retrieval_kind": "contradict"}),
        _seed("s-leak", "The capital of the federation is Veria, and the currency is the mark.", True, ["schema"], {"schema_violation": None}),
        _seed("s-redundant", "The reactor output is 3.8 gigawatts, within limits. (duplicate)", True, ["tool"], {"tool_error": False, "tool_result_sign": "positive"}),
    ]


class TestVerifiability:
    def test_checkable_and_true(self):
        v = assess_verifiability(_seed("x", "ok", True, ["tool"], {"tool_error": False}))
        assert v.checkable and v.verified

    def test_uncheckable(self):
        v = assess_verifiability(_seed("x", "no signals", True, [], {}))
        assert not v.checkable
        assert not v.verified

    def test_contradiction_fails_verification(self):
        v = assess_verifiability(_seed("x", "c", True, ["retrieval"], {"retrieval_kind": "contradict"}))
        assert v.checkable and not v.verified

    def test_gate_rejects_unverifiable(self):
        result = VerifiabilityGate().evaluate(_seed("x", "no signals", True, [], {}))
        assert not result.passed
        assert "checkable" in result.reason


class TestContamination:
    def test_ngram_overlap_detects_leak(self):
        assert ngram_overlap(HOLDOUT[0], HOLDOUT, 5) > 0.9
        assert ngram_overlap("totally different content here", HOLDOUT, 5) == 0.0

    def test_quarantines_leaked_seed(self):
        quarantine = InMemoryQuarantineStore()
        gate = ContaminationGate(holdout_corpus=HOLDOUT, quarantine=quarantine)
        result = gate.evaluate(_seed("q1", HOLDOUT[0], True))
        assert not result.passed
        assert "q1" in quarantine.list()
        assert "contamination" in quarantine.reasons()

    def test_clean_seed_passes(self):
        quarantine = InMemoryQuarantineStore()
        gate = ContaminationGate(holdout_corpus=HOLDOUT, quarantine=quarantine)
        result = gate.evaluate(_seed("c1", "a perfectly unique sentence about the weather", True))
        assert result.passed

    def test_minhash_similarity_reported(self):
        gate = ContaminationGate(holdout_corpus=HOLDOUT)
        result = gate.evaluate(_seed("m1", HOLDOUT[0], True))
        assert result.detail["minhash_similarity"] > 0.6


class TestDiversity:
    def test_duplicate_content_rejected(self):
        dg = DiversityGate(embedder=StubEmbedder())
        assert dg.evaluate(_seed("a", "unique content alpha")).passed
        assert not dg.evaluate(_seed("b", "unique content alpha")).passed  # near-duplicate
        assert dg.evaluate(_seed("c", "entirely different content beta")).passed

    def test_cluster_vectors(self):
        vecs = [[1.0, 0.0], [0.98, 0.02], [0.0, 1.0], [0.02, 0.98]]
        labels, report = cluster_vectors(vecs, distance_threshold=0.3)
        assert report.coverage == pytest.approx(0.5)


class TestLabelQuality:
    def test_sampled_and_reviewed(self):
        lg = LabelQualityGate(sample_rate=1.0, reviewer=AutoReviewer(), seed=1)
        result = lg.evaluate(_seed("l1", "x", True))
        assert result.passed
        assert lg.queue.decision_for("l1") is True


class TestIngestAndProvenance:
    def test_stamp(self):
        stamp = stamp_provenance(_seed("i1", "hello world"))
        assert stamp["seed_id"] == "i1"
        assert stamp["source"] == "test"
        assert len(stamp["content_sha256"]) == 64

    def test_static_source(self):
        seeds = StaticWorldSeedSource(seeds=_default_seeds()).fetch_seeds()
        assert len(seeds) == 5


class TestGatePipeline:
    def test_full_pipeline(self):
        seeds = _default_seeds()
        dataset, run = gate(
            seeds,
            GatePolicy(),
            holdout_corpus=HOLDOUT,
            seed=42,
        )
        assert dataset.summary is not None
        assert dataset.summary.total == 5
        accepted_ids = {s.sample_id for s in dataset.samples}
        # s-unverifiable rejected by verifiability; s-leak quarantined by
        # contamination; s-redundant rejected by diversity
        assert "s-ok" in accepted_ids
        assert "s-unverifiable" not in accepted_ids
        assert "s-contradicted" not in accepted_ids
        assert "s-leak" not in accepted_ids
        assert "s-redundant" not in accepted_ids
        assert dataset.summary.rejected_by_gate["verifiability"] == 2  # unverifiable + contradicted
        assert dataset.summary.rejected_by_gate["contamination"] == 1
        assert dataset.summary.rejected_by_gate["diversity"] >= 1
        assert dataset.summary.quarantine_reasons.get("contamination") == 1

    def test_provenance_lineage_recorded(self):
        seeds = _default_seeds()[:2]
        tracker = InMemoryProvenanceTracker()
        dataset, run = gate(seeds, GatePolicy(diversity=False), provenance=tracker, seed=1)
        rec = tracker.get("s-ok")
        assert rec is not None
        stages = [e.stage for e in rec.events]
        assert "ingest" in stages
        assert "verifiability" in stages
        assert "label_quality" in stages
        assert rec.dataset_version is not None
        assert dataset.provenance["s-ok"].sample_id == "s-ok"

    def test_policy_can_disable_gates(self):
        seeds = [_seed("x1", "content unique here", True, [], {})]
        dataset, _ = gate(seeds, GatePolicy(verifiability=False, contamination=False, diversity=False, label_quality=False))
        assert len(dataset.samples) == 1

    def test_jsonl_round_trip(self, tmp_path):
        dataset, _ = gate(_default_seeds(), GatePolicy(), holdout_corpus=HOLDOUT, seed=3)
        path = dataset.to_jsonl(tmp_path / "ds.jsonl")
        reloaded = dataset.from_jsonl(path)
        assert [s.sample_id for s in reloaded.samples] == [s.sample_id for s in dataset.samples]

    def test_summary_counts(self):
        dataset, run = gate(_default_seeds(), GatePolicy(), holdout_corpus=HOLDOUT, seed=4)
        assert dataset.summary.accepted + dataset.summary.rejected == dataset.summary.total
        assert len(dataset.samples) == dataset.summary.accepted

    def test_default_holdout_corpus_applies(self):
        # a seed that matches the built-in default holdout corpus must be
        # quarantined even when the caller passes no holdout_corpus
        seeds = [_seed("s-leak2", "Protocol 7 requires all telemetry to be signed before transmission.", True, ["tool"], {"tool_error": False})]
        dataset, run = gate(seeds, GatePolicy(), seed=5)
        assert len(dataset.samples) == 0
        assert dataset.summary.rejected_by_gate["contamination"] == 1

    def test_gate_order_short_circuits(self):
        seeds = [_seed("s1", HOLDOUT[0], True, ["tool"], {"tool_error": True})]
        dataset, run = gate(seeds, GatePolicy(), holdout_corpus=HOLDOUT, seed=5)
        verdicts = run.verdicts["s1"]
        assert verdicts[0].gate == "verifiability"
        assert not verdicts[0].passed  # tool_error fails the checkable-and-true
