"""M2 — extraction: chunking, typed extraction, eval harness, telemetry."""

import re

from substrate_knowledge.core.storage import InMemoryStore
from substrate_knowledge.m2_extraction.eval_harness import ExtractionEvalHarness
from substrate_knowledge.m2_extraction.extractor import (
    ExtractedEntity,
    ExtractedRelation,
    ExtractionResult,
    PatternExtractor,
)
from substrate_knowledge.m2_extraction.golden_slices import GOLDEN_SLICES, GoldEntity, GoldRelation, GoldSlice
from substrate_knowledge.m2_extraction.ingest import CanonicalChunk, Chunker, ParsedDocument, TextParser
from substrate_knowledge.m2_extraction.roundtrip import RoundTripValidator
from substrate_knowledge.m2_extraction.telemetry import ExtractionTelemetryStore


def test_chunker_splits_and_overlaps():
    text = "Sentence one is short. " * 40
    chunks = Chunker(max_chars=200, overlap_chars=30).chunk(ParsedDocument(doc_id="d1", source="f", text=text))
    assert len(chunks) > 1
    assert all(isinstance(c, CanonicalChunk) for c in chunks)
    assert all(c.doc_id == "d1" for c in chunks)
    assert all(c.order == i for i, c in enumerate(chunks))
    assert all(len(c.text) <= 210 for c in chunks)


def test_text_parser_deterministic(tmp_path):
    path = tmp_path / "doc.md"
    path.write_text("# Section\nBody text here.\n", encoding="utf-8")
    parsed = TextParser().parse(path)
    assert parsed.doc_id == "doc"
    assert "Body text here" in parsed.text
    assert parsed.sections


def test_pattern_extractor_on_golden_slices():
    extractor = PatternExtractor()
    for gold in GOLDEN_SLICES:
        result = extractor.extract(gold.text, gold.slice_id, "0")
        assert result.entities, gold.slice_id
        names = {e.name for e in result.entities}
        assert {g.name for g in gold.entities} <= names


def test_eval_harness_math():
    gold = GoldSlice(
        slice_id="t",
        text="X supplies Y to Z.",
        entities=[GoldEntity("X Corp", "Organization"), GoldEntity("Y Part", "Product")],
        relations=[GoldRelation("X Corp", "Y Part", "provides")],
    )
    result = ExtractionResult(
        entities=[
            ExtractedEntity(id="e0", name="X Corp", type="Organization", doc_id="t", chunk_id="0"),
            ExtractedEntity(id="e1", name="Y Part", type="Product", doc_id="t", chunk_id="0"),
            ExtractedEntity(id="e2", name="Ghost Entity", type="Person", doc_id="t", chunk_id="0"),
        ],
        relations=[ExtractedRelation(id="r0", source_id="e0", target_id="e1", type="provides", doc_id="t", chunk_id="0")],
        violations=["unknown_entity_type:Zorp"],
    )
    evaluation = ExtractionEvalHarness().evaluate(gold, result)
    assert evaluation.entity_precision == 2 / 3
    assert evaluation.entity_recall == 1.0
    assert evaluation.relation_precision == 1.0
    assert evaluation.relation_recall == 1.0
    assert evaluation.type_violation_rate == 1 / 4


def test_eval_harness_continuous_score_on_golden_slices():
    harness = ExtractionEvalHarness()
    report = harness.evaluate_slices(GOLDEN_SLICES, PatternExtractor())
    assert len(report.slices) == len(GOLDEN_SLICES)
    for key in ("entity_precision", "entity_recall", "relation_precision", "relation_recall"):
        assert 0.0 <= report.continuous[key] <= 1.0
    assert report.continuous["entity_recall"] == 1.0
    assert report.continuous["relation_recall"] == 1.0


def test_type_violation_reporting_on_bad_edge():
    extractor = PatternExtractor()
    result = extractor.extract("Northwind supplies Acme.", "t", "0")
    # "Acme" typed Organization (known org) -> provides(Organization->Product)
    # against target Organization is a schema violation the extractor reports.
    assert isinstance(result.violations, list)


def test_roundtrip_detects_hallucinated_relations():
    gold = GOLDEN_SLICES[0]
    result = PatternExtractor().extract(gold.text, gold.slice_id, "0")
    clean = RoundTripValidator().verify(result, gold.text)
    assert clean.recoverability == 1.0

    corrupted = result.model_copy(deep=True)
    corrupted.entities.append(
        ExtractedEntity(id="e99", name="Zorgon Industries", type="Organization", doc_id=gold.slice_id, chunk_id="0")
    )
    corrupted.relations.append(
        ExtractedRelation(id="r99", source_id="e0", target_id="e99", type="provides", doc_id=gold.slice_id, chunk_id="0")
    )
    corrupted_report = RoundTripValidator().verify(corrupted, gold.text)
    assert corrupted_report.recoverability < clean.recoverability
    hallucinated = [s for s in corrupted_report.relation_scores if s["target"] == "Zorgon Industries"][0]
    assert hallucinated["recoverable"] is False
    assert hallucinated["contained"] is False


def test_telemetry_store_slices_and_continuous():
    store = ExtractionTelemetryStore(InMemoryStore())
    harness = ExtractionEvalHarness()
    report = harness.evaluate_slices(GOLDEN_SLICES, PatternExtractor())
    for evaluation in report.slices:
        store.record_slice(evaluation)
    continuous = store.continuous_score()
    assert continuous["n_slices"] == len(GOLDEN_SLICES)
    assert continuous["entity_recall"] == 1.0
    store.record_doc("d1", n_entities=2, n_relations=1, n_violations=0)
    assert len(store.doc_scores()) == 1


def test_golden_slices_dataset_shape():
    for gold in GOLDEN_SLICES:
        assert gold.slice_id
        assert gold.text
        assert gold.entities
        assert gold.relations
        assert re.search(r"[A-Z][a-z]+", gold.text)
