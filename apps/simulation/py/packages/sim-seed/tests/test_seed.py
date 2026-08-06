import json

import pytest
from fastapi.testclient import TestClient

from sim_seed import (
    coherence_lint,
    seed_synth_app,
    validate_world_doc,
)
from sim_seed.schema import ValidationError
from sim_seed.synth import SeedSynthesizer
from sim_shared.llm import LLMResponse, OpenAICompatClient, LLMUnavailableError


def _snapshot():
    return {
        "as_of": "2020-01-01",
        "world_id": "w-us-2020",
        "series": [
            {"series_id": "UNRATE", "value": 3.6, "units": "percent"},
            {"series_id": "RSAFS_INDEX", "value": 102.5, "units": "index"},
        ],
    }


def _valid_doc():
    return {
        "schema_version": "1.0.0",
        "world_id": "w",
        "generated_at": "2026-01-01T00:00:00Z",
        "macro_snapshot": {"as_of": "2020-01-01", "series": [{"series_id": "UNRATE", "value": 3.6}]},
        "narrative": {
            "economy": "Growth is steady.",
            "labor": "Unemployment sits at 3.6 percent.",
            "consumers": "Spending is strong.",
            "supply_chain": "Supply chains are normal.",
            "sentiment": "Confidence is high.",
        },
        "inferred_risks": {"cascade": 0.2, "shift_magnitude": 0.1},
    }


def test_schema_validation_rejects_missing_sections():
    doc = _valid_doc()
    del doc["narrative"]["labor"]
    with pytest.raises(ValidationError):
        validate_world_doc(doc)


def test_schema_validation_rejects_bad_version():
    doc = _valid_doc()
    doc["schema_version"] = "9.9.9"
    with pytest.raises(ValidationError):
        validate_world_doc(doc)


def test_coherence_lint_flags_lookahead():
    doc = _valid_doc()
    doc["narrative"]["economy"] = "In April 2020 unemployment will spike to 14.7."
    issues = coherence_lint(doc)
    assert any("lookahead-violation" in i for i in issues)


def test_coherence_lint_clean_doc():
    assert coherence_lint(_valid_doc()) == []


def test_coherence_lint_flags_risk_out_of_bounds():
    doc = _valid_doc()
    doc["inferred_risks"]["cascade"] = 1.5
    assert any("cascade" in i for i in coherence_lint(doc))


class _StubLLM:
    def __init__(self, text):
        self._text = text

    def chat(self, messages, model=None, temperature=0.7, max_tokens=512):
        return LLMResponse(text=self._text, model=model or "stub")


def test_synthesizer_validates_and_lints_output():
    stub = _StubLLM(
        json.dumps(
            {
                "narrative": {
                    "economy": "Growth is steady.",
                    "labor": "Unemployment is 3.6 percent.",
                    "consumers": "Spending is strong.",
                    "supply_chain": "Supply chains are normal.",
                    "sentiment": "Confidence is high.",
                },
                "inferred_risks": {"cascade": 0.2, "shift_magnitude": 0.1},
            }
        )
    )
    synth = SeedSynthesizer(client=stub)
    doc = synth.synthesize(_snapshot())
    assert doc["schema_version"] == "1.0.0"
    assert doc["prompt_version"] == "1.0.0"
    assert doc["macro_snapshot"]["as_of"] == "2020-01-01"
    assert doc["coherence_issues"] == []


def test_synthesizer_without_client_raises():
    synth = SeedSynthesizer(client=None)
    with pytest.raises(LLMUnavailableError):
        synth.synthesize(_snapshot())


def test_synthesizer_rejects_non_json():
    stub = _StubLLM("definitely not json")
    with pytest.raises(LLMUnavailableError):
        SeedSynthesizer(client=stub).synthesize(_snapshot())


def test_synth_api_schema_endpoint():
    client = TestClient(seed_synth_app)
    r = client.get("/schema")
    assert r.status_code == 200
    assert r.json()["$id"].endswith("world-doc-1.0.0.json")


def test_synth_api_no_llm_returns_503():
    client = TestClient(seed_synth_app)
    r = client.post("/synth", json=_snapshot())
    assert r.status_code == 503