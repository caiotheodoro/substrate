"""C — micro-adapter two-gate loop (Airbnb Layer 3, evolve of r5).

The seed: a patch must pass BOTH gates to ship — no regression on
expert-reviewed domains AND no high-uncertainty outputs shipping unflagged.
Canary lane = 01's escalation band. Lifecycle rules (fuse / retrain on
accumulation / unload unused) are tracked and tested.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trust.gated_data.micro_patch import (
    MAX_PATCHES_PER_CATEGORY,
    PatchLifecycle,
    decide_micro_patch,
    evaluate_domains,
    flag_uncertain,
)


def _domains() -> dict[str, list[tuple[list[float], bool]]]:
    """Two expert-reviewed domains with known outcomes.

    - finance: outcomes follow the feature sign (confidence = feature).
    - retrieval: same structure, different calibration.
    """
    return {
        "finance": [([0.9], True), ([0.1], False), ([0.8], True), ([0.2], False)],
        "retrieval": [([0.85], True), ([0.15], False), ([0.7], True), ([0.3], False)],
    }


def _incumbent(features: list[list[float]]) -> list[float]:
    return [f[0] for f in features]


class TestNoRegressionGate:
    def test_candidate_matching_incumbent_passes(self):
        result = evaluate_domains(_incumbent, _domains(), _incumbent)
        assert result.passed

    def test_candidate_regressing_one_domain_fails(self):
        def bad_candidate(features):
            # worse on finance: pushes all confidence toward 0.5
            return [abs(f[0] - 0.5) + 0.5 for f in features]

        result = evaluate_domains(bad_candidate, _domains(), _incumbent)
        assert not result.passed
        finance = next(d for d in result.domains if d.domain == "finance")
        assert finance.regressed

    def test_candidate_improving_everywhere_passes(self):
        # sharpen confidence toward the true outcome (clamped): better Brier
        def good_candidate(features):
            return [min(max(0.5 + (f[0] - 0.5) * 1.2, 0.05), 0.95) for f in features]

        result = evaluate_domains(good_candidate, _domains(), _incumbent)
        assert result.passed
        for d in result.domains:
            assert d.candidate_accuracy >= d.incumbent_accuracy


class TestUncertaintyGate:
    def test_flags_high_variance_samples(self):
        flags = flag_uncertain(
            {"s1": 0.5},
            {"s1": 0.05, "s2": 0.001},
            threshold=0.01,
        )
        assert [f.sample_id for f in flags] == ["s1"]
        assert flags[0].action == "human-review"

    def test_no_flags_below_threshold(self):
        assert flag_uncertain({}, {"s1": 0.001}, threshold=0.01) == []


class TestTwoGateDecision:
    def test_patch_ships_when_both_gates_pass(self):
        verdict = decide_micro_patch(
            "mp-1",
            "finance phrasing bug",
            "finance",
            _domains(),
            _incumbent,
            _incumbent,
            {"s1": 0.001, "s2": 0.002},
        )
        assert verdict.shipped
        assert verdict.canary_lane == "escalation-band"
        assert verdict.no_regression.passed
        assert not verdict.flagged_for_human_review

    def test_patch_blocked_by_regression(self):
        def bad_candidate(features):
            return [abs(f[0] - 0.5) + 0.5 for f in features]

        verdict = decide_micro_patch(
            "mp-2",
            "regressing patch",
            "finance",
            _domains(),
            bad_candidate,
            _incumbent,
            {"s1": 0.001},
        )
        assert not verdict.shipped
        assert verdict.canary_lane is None

    def test_patch_blocked_by_uncertainty(self):
        verdict = decide_micro_patch(
            "mp-3",
            "uncertain outputs",
            "finance",
            _domains(),
            _incumbent,
            _incumbent,
            {"s1": 0.05},  # high judge variance → human review
        )
        assert not verdict.shipped
        assert verdict.flagged_for_human_review


class TestLifecycle:
    def test_retrain_on_accumulation(self):
        life = PatchLifecycle()
        for i in range(MAX_PATCHES_PER_CATEGORY):
            life.register(f"mp-{i}", "finance")
        assert life.needs_retrain("finance")
        assert not life.needs_retrain("retrieval")

    def test_fusion_candidates_for_co_triggering(self):
        life = PatchLifecycle()
        life.register("mp-a", "finance", co_triggers=["mp-b"])
        life.register("mp-b", "finance", co_triggers=["mp-a"])
        life.register("mp-a", "finance", co_triggers=["mp-b"])
        life.register("mp-b", "finance", co_triggers=["mp-a"])
        life.register("mp-a", "finance", co_triggers=["mp-b"])
        life.register("mp-b", "finance", co_triggers=["mp-a"])
        assert ("mp-a", "mp-b") in life.co_trigger_counts
        assert life.fusion_candidates(min_co_triggers=3) == [["mp-a", "mp-b"]]

    def test_unload_unused_patches(self):
        life = PatchLifecycle()
        now = datetime.now(timezone.utc)
        life.register("mp-old", "finance", triggered_at=(now - timedelta(days=10)).isoformat())
        life.register("mp-fresh", "finance", triggered_at=now.isoformat())
        stale = life.unload_unused(stale_after_days=7, now=now.isoformat())
        assert stale == ["mp-old"]
