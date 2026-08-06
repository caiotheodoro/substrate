"""M2 extractors: tool-call verifier (A-T-14), schema checker (A-T-16),
retrieval ladder (A-T-15), evidence features (A-T-17)."""
import pytest

from trust.evidence_features import EvidenceFeatures, OutcomeHistory, build_evidence_features, validate_against_registry
from trust.extractors.retrieval_ladder import LadderRung, RetrievalLadder
from trust.extractors.schema_checker import SchemaCheck, check_schema
from trust.extractors.tool_call_verifier import ToolCallRecord, verify_tool_call
from trust.model_backend import DeterministicVerdictBackend, parse_verdict_json


class TestToolCallVerifier:
    def test_success_with_matching_sign(self):
        v = verify_tool_call(
            ToolCallRecord(call_id="c1", tool_name="calc", status="success", result={"value": 42}, expected_sign="positive")
        )
        assert v.as_dict() == {"ran": True, "result_sign": True, "error": False, "result_schema_ok": True}

    def test_sign_mismatch(self):
        v = verify_tool_call(ToolCallRecord(call_id="c1", tool_name="calc", status="success", result=-3, expected_sign="positive"))
        assert v.result_sign is False

    def test_error_status(self):
        v = verify_tool_call(ToolCallRecord(call_id="c1", tool_name="calc", status="error", result=None, error_message="boom"))
        assert v.error is True
        assert v.ran is False

    def test_numeric_string_result(self):
        v = verify_tool_call(ToolCallRecord(call_id="c1", tool_name="calc", status="success", result="-3.5", expected_sign="negative"))
        assert v.result_sign is True

    def test_non_numeric_result_fails_sign(self):
        v = verify_tool_call(ToolCallRecord(call_id="c1", tool_name="fetch", status="success", result={"text": "hello"}, expected_sign="any"))
        assert v.result_sign is False

    def test_schema_violation_detected(self):
        schema = {"type": "object", "required": ["amount"], "properties": {"amount": {"type": "number"}}}
        v = verify_tool_call(ToolCallRecord(call_id="c1", tool_name="calc", status="success", result={"amount": "not-a-number"}, result_schema=schema))
        assert v.result_schema_ok is False

    def test_schema_ok(self):
        schema = {"type": "object", "required": ["amount"], "properties": {"amount": {"type": "number"}}}
        v = verify_tool_call(ToolCallRecord(call_id="c1", tool_name="calc", status="success", result={"amount": 5}, result_schema=schema))
        assert v.result_schema_ok is True

    def test_invalid_schema_is_violation(self):
        v = verify_tool_call(ToolCallRecord(call_id="c1", tool_name="calc", status="success", result={}, result_schema={"type": 123}))
        assert v.result_schema_ok is False


class TestSchemaChecker:
    def test_valid(self):
        check = check_schema({"amount": 5}, {"type": "object", "properties": {"amount": {"type": "number"}}})
        assert check == SchemaCheck(True, "none")

    def test_missing_required(self):
        check = check_schema({}, {"type": "object", "required": ["amount"]})
        assert check.satisfied is False
        assert check.violation_kind == "missing"

    def test_type_violation(self):
        check = check_schema({"amount": "x"}, {"type": "object", "properties": {"amount": {"type": "number"}}})
        assert check.violation_kind == "type"

    def test_enum_violation(self):
        check = check_schema({"mode": "bogus"}, {"type": "object", "properties": {"mode": {"enum": ["a", "b"]}}})
        assert check.violation_kind == "enum"

    def test_format_violation(self):
        check = check_schema({"email": "not-an-email"}, {"type": "object", "properties": {"email": {"type": "string", "format": "email"}}})
        assert check.violation_kind == "format"

    def test_malformed_schema(self):
        check = check_schema({}, {"type": 123})
        assert check.satisfied is False
        assert check.violation_kind == "other"


class TestRetrievalLadder:
    def _ladder(self):
        return RetrievalLadder(
            [
                LadderRung("hhem-2.1", DeterministicVerdictBackend(floor=0.05), escalate_below=0.7),
                LadderRung("glider-3.8b", DeterministicVerdictBackend(floor=0.1, noise=0.1), escalate_below=0.9),
            ]
        )

    def test_cheap_rung_answers_first(self):
        v, trace = self._ladder().verdict("the reactor is safe", ["The report confirms the reactor is safe and stable."])
        assert trace.rungs_used[0] == "hhem-2.1"
        assert v.kind in ("support", "contradict", "silent")

    def test_escalation_happens_on_low_prob(self):
        v, trace = self._ladder().verdict("zzz qqq unknownclaim", ["nothing here at all"])
        assert len(trace.rungs_used) >= 1

    def test_contradiction_keyword(self):
        v, _ = self._ladder().verdict("the reactor is safe", ["The telemetry says the opposite: the reactor is NOT safe, contradicting the claim."])
        assert v.kind == "contradict"

    def test_c3_shape(self):
        v, _ = self._ladder().verdict("claim", ["support doc"])
        d = v.as_dict()
        assert set(d) == {"kind", "prob", "citedEvidence", "claim"}
        assert 0.0 <= v.prob <= 1.0


class TestParseVerdictJson:
    def test_valid_json(self):
        v = parse_verdict_json('{"kind": "support", "prob": 0.9, "citedEvidence": "d1"}', "claim")
        assert v.kind == "support"
        assert v.prob == 0.9

    def test_malformed_defaults_silent(self):
        v = parse_verdict_json("not json at all", "claim")
        assert v.kind == "silent"
        assert v.prob == 0.5

    def test_bad_kind_defaults_silent(self):
        v = parse_verdict_json('{"kind": "maybe", "prob": 0.9}', "claim")
        assert v.kind == "silent"


class TestEvidenceFeatures:
    def test_all_channels_aligned_to_registry(self):
        feats = build_evidence_features(
            tool=verify_tool_call(ToolCallRecord(call_id="c", tool_name="t", status="success", result=5)),
            retrieval=parse_verdict_json('{"kind": "support", "prob": 0.9}', "c"),
            schema=check_schema({"a": 1}, {"type": "object"}),
            outcome_history=OutcomeHistory(history=[True, True, False]),
        )
        row = feats.to_row()
        assert set(row) == {
            "tool_call_ran",
            "tool_call_success",
            "tool_result_sign_ok",
            "tool_result_schema_ok",
            "tool_error",
            "retrieval_kind_support",
            "retrieval_kind_contradict",
            "retrieval_kind_silent",
            "retrieval_prob",
            "schema_satisfied",
            "schema_violation_missing",
            "schema_violation_type",
            "schema_violation_enum",
            "outcomes_history_rate",
            "outcomes_history_n",
            "outcomes_recent_rate",
        }
        assert row["tool_call_ran"] == 1.0
        assert row["retrieval_kind_support"] == 1.0
        assert row["outcomes_history_rate"] == pytest.approx(2 / 3)
        assert row["schema_satisfied"] == 1.0

    def test_absent_channels_are_zero_not_silent(self):
        feats = build_evidence_features()
        row = feats.to_row()
        assert row["retrieval_kind_silent"] == 0.0
        assert row["tool_call_ran"] == 0.0
        assert row["outcomes_history_rate"] == 0.0

    def test_silent_is_distinct_from_absent(self):
        silent = build_evidence_features(retrieval=parse_verdict_json('{"kind": "silent", "prob": 0.5}', "c")).to_row()
        assert silent["retrieval_kind_silent"] == 1.0

    def test_registry_validation(self):
        validate_against_registry({"tool_call_ran": 1.0})
        with pytest.raises(ValueError):
            validate_against_registry({"logprob_norm": 0.9})

    def test_vector_alignment(self):
        from trust.contracts import FEATURE_NAMES

        feats = build_evidence_features()
        vec = feats.vector()
        assert vec.shape == (len(FEATURE_NAMES),)
        assert float(vec[0]) == 0.0

    def test_outcome_history_recent(self):
        h = OutcomeHistory(history=[True, True, False, True, False])
        assert h.rate == pytest.approx(0.6)
        assert h.recent_rate == pytest.approx(0.6)  # all 5 inside the window
