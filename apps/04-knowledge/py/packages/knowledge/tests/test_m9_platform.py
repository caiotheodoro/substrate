"""M9 — platform: LLM provider stub, message bus, knowctl CLI."""

import json

from pydantic import BaseModel, Field
from typer.testing import CliRunner

from substrate_knowledge.m9_platform.bus import InMemoryBus, TOPICS, get_bus
from substrate_knowledge.m9_platform.cli import app
from substrate_knowledge.m9_platform.llm import LLMProvider

runner = CliRunner()


def test_llm_provider_stub_complete_and_structured():
    provider = LLMProvider(stub=True)
    text = provider.complete([{"role": "user", "content": "hello"}])
    assert isinstance(text, str) and text.startswith("deterministic stub")
    assert provider.complete([{"role": "user", "content": "hello"}]) == text

    class Model(BaseModel):
        name: str = "default-name"
        score: float = 0.5

    parsed = provider.structured(Model, "do something")
    assert isinstance(parsed, Model)


def test_llm_provider_stub_embeddings_deterministic():
    provider = LLMProvider(stub=True)
    assert provider.embed("acme logistics").shape == (128,)
    assert (provider.embed("acme logistics") == provider.embed("acme logistics")).all()
    assert not (provider.embed("acme logistics") == provider.embed("northwind freight")).all()


def test_in_memory_bus_topics_and_dispatch():
    bus = InMemoryBus()
    received = []
    bus.subscribe("gate.verdict", lambda event: received.append(event["payload"]))
    bus.publish("gate.verdict", {"kind": "support", "prob": 0.9})
    assert len(received) == 1
    assert bus.history("gate.verdict")[0]["payload"]["kind"] == "support"
    assert set(TOPICS) == {"source.changed", "document.parsed", "extraction.complete", "gate.verdict"}


def test_bus_factory_memory_default():
    assert isinstance(get_bus("memory"), InMemoryBus)
    assert isinstance(get_bus(), InMemoryBus)


def test_knowctl_gate_command():
    result = runner.invoke(
        app, ["gate", "--claim", "Acme profits rose sharply", "--evidence", "Acme reported strong growth and rising profits"]
    )
    assert result.exit_code == 0
    assert "support" in result.stdout


def test_knowctl_gate_json():
    result = runner.invoke(
        app,
        ["gate", "--claim", "Acme profits declined", "--evidence", "Acme reported strong growth", "--json"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert set(payload) == {"kind", "prob", "citedEvidence", "claim"}
    assert payload["kind"] == "contradict"


def test_knowctl_characterize(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for i in range(10):
        (corpus / f"doc-{i}.txt").write_text(f"Acme and Northwind partner on document {i}.", encoding="utf-8")
    result = runner.invoke(app, ["characterize", str(corpus)])
    assert result.exit_code == 0
    assert "architecture" in result.stdout


def test_knowctl_eval_extraction():
    result = runner.invoke(app, ["eval-extraction", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert "continuous" in payload
    assert payload["continuous"]["entity_recall"] == 1.0


def test_knowctl_bench_writes_validation(tmp_path):
    outdir = tmp_path / "validation"
    result = runner.invoke(app, ["bench", "--outdir", str(outdir)])
    assert result.exit_code == 0
    assert (outdir / "r1_graph_vs_flat.json").exists()
    assert (outdir / "r2_error_propagation.json").exists()
    r1 = json.loads((outdir / "r1_graph_vs_flat.json").read_text())
    results = {r["corpus"]: r for r in r1["results"]}
    assert results["multi-hop"]["graph"]["evidence_recall"] == 1.0
    assert results["multi-hop"]["flat"]["evidence_recall"] == 0.0
    assert results["semantic"]["flat"]["evidence_recall"] == 1.0
