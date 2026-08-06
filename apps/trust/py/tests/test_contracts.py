"""C2/C3/C5 contract shapes + gate boundaries (mirrors packages/substrate)."""
import pytest

from trust.contracts import (
    ConfidenceRequest,
    ConfidenceResponse,
    DecisionRecord,
    RetrievalVerdict,
    band_for,
    gate,
)


class TestGate:
    def test_execute_above_threshold(self):
        assert gate(0.9, 0.7, 0.3) == "execute"

    def test_reject_below_threshold(self):
        assert gate(0.2, 0.7, 0.3) == "reject"

    def test_escalation_band_between(self):
        assert gate(0.5, 0.7, 0.3) == "escalate"

    def test_boundary_execute(self):
        assert gate(0.7, 0.7, 0.3) == "execute"

    def test_boundary_reject_exclusive(self):
        assert gate(0.3, 0.7, 0.3) == "escalate"

    def test_band_for_maps_to_c5_bands(self):
        assert band_for(0.9, 0.7, 0.3) == "execute-band"
        assert band_for(0.5, 0.7, 0.3) == "escalation-band"
        assert band_for(0.1, 0.7, 0.3) == "reject-band"

    def test_out_of_range_confidence_rejected(self):
        with pytest.raises(ValueError):
            gate(1.5, 0.7, 0.3)
        with pytest.raises(ValueError):
            gate(-0.1, 0.7, 0.3)

    def test_inverted_thresholds_rejected(self):
        with pytest.raises(ValueError):
            gate(0.5, 0.3, 0.7)


class TestRetrievalVerdict:
    def test_as_dict_round_trip(self):
        v = RetrievalVerdict("support", 0.93, "doc-7", "the claim")
        data = v.as_dict()
        assert RetrievalVerdict.from_dict(data) == v

    def test_bad_kind_rejected(self):
        with pytest.raises(ValueError):
            RetrievalVerdict.from_dict({"kind": "vibes", "prob": 0.5})

    def test_prob_clamped_from_dict(self):
        v = RetrievalVerdict.from_dict({"kind": "silent", "prob": 2.0})
        assert v.prob == 2.0  # shape stays faithful; downstream clips


class TestDecisionRecord:
    def test_c2_shape(self):
        r = DecisionRecord(
            decisionId="d-1",
            turnId="t-1",
            action="run_check",
            confidenceFeatures={"tool_call_ran": 1.0},
            verdict="execute",
            outcome=None,
            confirmedAt=None,
        )
        d = r.as_dict()
        assert d["verdict"] == "execute"
        assert d["outcome"] is None
        assert d["confirmedAt"] is None


class TestConfidenceResponse:
    def test_c5_shape(self):
        resp = ConfidenceResponse(score=0.83, band="execute-band", explain={"tool_call_ran": 0.1}, modelVersion="v1")
        d = resp.as_dict()
        assert d["score"] == 0.83
        assert d["band"] in ("execute-band", "escalation-band", "reject-band")
        assert "explain" in d and "modelVersion" in d

    def test_request_shape(self):
        req = ConfidenceRequest(decisionId="d-1", confidenceFeatures={"schema_satisfied": 1.0})
        assert req.decisionId == "d-1"
