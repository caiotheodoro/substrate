"""M5 recalibration loop: consumer (A-T-30), reconciler (A-T-31),
scheduler + band drift (A-T-32)."""
from datetime import datetime, timedelta, timezone

from trust.contracts import DecisionRecord
from trust.recalib.decision_log import DecisionLogConsumer, InMemoryDecisionLogSource, OutcomeStore
from trust.recalib.reconciler import OutcomeReconciler
from trust.recalib.scheduler import band_drift_report, trigger_retrain

NOW = "2026-06-01T12:00:00+00:00"
PAST = (datetime.fromisoformat(NOW) - timedelta(days=10)).isoformat()


def _decision(did, outcome=None, confirmed_at=None, verdict="execute", score=0.5, features=None):
    return DecisionRecord(
        decisionId=did,
        turnId=f"t-{did}",
        action="a",
        confidenceFeatures=dict(features or {"score": score, "tool_call_ran": 1.0}),
        verdict=verdict,
        outcome=outcome,
        confirmedAt=confirmed_at,
    )


class TestReconciler:
    def test_pending(self):
        r = OutcomeReconciler().reconcile(_decision("d1"), now=NOW, arrived_at=NOW)
        assert r.state == "pending"

    def test_delayed_after_ttl(self):
        r = OutcomeReconciler(staleness_ttl_seconds=86400).reconcile(_decision("d1"), now=NOW, arrived_at=PAST)
        assert r.state == "delayed"
        assert r.age_seconds > 0

    def test_confirmed(self):
        r = OutcomeReconciler().reconcile(_decision("d1", outcome=True, confirmed_at=NOW))
        assert r.state == "confirmed"

    def test_conflicting_outcome_without_confirmed_at(self):
        r = OutcomeReconciler().reconcile(_decision("d1", outcome=True, confirmed_at=None))
        assert r.state == "conflicting"

    def test_conflicting_rejected_but_true(self):
        r = OutcomeReconciler().reconcile(_decision("d1", outcome=True, confirmed_at=NOW, verdict="reject"))
        assert r.state == "conflicting"

    def test_reconcile_many_counts(self):
        rows = [
            _decision("d1", outcome=True, confirmed_at=NOW),
            _decision("d2"),
            _decision("d3", outcome=False, confirmed_at=None),
        ]
        counts = OutcomeReconciler().reconcile_many(rows, now=NOW, arrived_at=NOW)
        assert counts == {"pending": 1, "confirmed": 1, "delayed": 0, "conflicting": 1}


class TestConsumer:
    def test_poll_consumes_and_advances_cursor(self):
        source = InMemoryDecisionLogSource([_decision("d1", outcome=True), _decision("d2")])
        consumer = DecisionLogConsumer(source)
        assert consumer.poll_once() == 2
        assert len(consumer.store.records) == 2
        # second poll sees nothing new
        assert consumer.poll_once() == 0

    def test_duplicates_skipped(self):
        source = InMemoryDecisionLogSource([_decision("d1"), _decision("d1")])
        consumer = DecisionLogConsumer(source)
        assert consumer.poll_once() == 1

    def test_training_frame_only_labeled(self):
        store = OutcomeStore()
        store.add(_decision("d1", outcome=True, confirmed_at=NOW))
        store.add(_decision("d2"))
        features, labels = store.training_frame()
        assert len(labels) == 1
        assert labels == [True]
        assert features[0]["tool_call_ran"] == 1.0


class TestBandDrift:
    def test_per_band_accuracy(self):
        rows = [
            _decision("d1", outcome=True, confirmed_at=NOW, score=0.9),
            _decision("d2", outcome=False, confirmed_at=NOW, score=0.85),
            _decision("d3", outcome=False, confirmed_at=NOW, score=0.5),
            _decision("d4", outcome=True, confirmed_at=NOW, score=0.1),
        ]
        report = band_drift_report(rows)
        assert report.per_band["execute-band"]["accuracy"] == 0.5
        assert report.per_band["escalation-band"]["accuracy"] == 0.0
        assert report.per_band["reject-band"]["accuracy"] == 1.0
        assert report.n_labeled == 4

    def test_trigger_retrain(self, tmp_path):
        store = OutcomeStore()
        for i in range(30):
            outcome = i % 3 == 0
            store.add(_decision(f"d{i:02d}", outcome=outcome, confirmed_at=NOW, score=0.5 if outcome else 0.9))
        calls = []

        def fake_train(features, labels):
            calls.append((features, labels))
            return {"features": features, "labels": labels}

        report = trigger_retrain(store, fake_train, current_version="v0", out_dir=str(tmp_path))
        assert report.n_labels == 30
        assert report.old_version == "v0"
        assert report.new_version.startswith("v")
        assert (tmp_path / report.saved_artifact).exists()
        assert len(calls) == 1

    def test_trigger_retrain_needs_min_labels(self, tmp_path):
        store = OutcomeStore()
        for i in range(5):
            store.add(_decision(f"d{i}", outcome=True, confirmed_at=NOW))
        import pytest

        with pytest.raises(ValueError, match="not enough confirmed outcomes"):
            trigger_retrain(store, lambda f, y: None, out_dir=str(tmp_path))


class TestJudgeRecalibrationTrigger:
    def test_trigger_records_agreement_and_flags_below_target(self):
        from trust.recalib.scheduler import trigger_judge_recalibration

        report = trigger_judge_recalibration(
            lambda: {"kappa": 0.82, "alpha": 0.79, "n_cases": 15, "n_disagreements": 4},
            target=0.85,
        )
        assert report.kappa == 0.82
        assert report.needs_refinement is True  # below high-80s target → loop re-runs
        assert report.triggered_at  # the periodic hook records when

    def test_trigger_above_target_is_clean(self):
        from trust.recalib.scheduler import trigger_judge_recalibration

        report = trigger_judge_recalibration(
            lambda: {"kappa": 0.91, "alpha": 0.89, "n_cases": 20, "n_disagreements": 2},
            target=0.85,
        )
        assert report.needs_refinement is False
        assert report.as_dict()["kappa"] == 0.91

    def test_trigger_serializes_for_band_drift_artifact(self):
        from trust.recalib.scheduler import trigger_judge_recalibration

        report = trigger_judge_recalibration(
            lambda: {"kappa": 0.7, "alpha": 0.65, "n_cases": 10, "n_disagreements": 3}
        )
        d = report.as_dict()
        assert set(d) == {
            "kappa",
            "alpha",
            "n_cases",
            "n_disagreements",
            "target",
            "needs_refinement",
            "triggered_at",
        }
