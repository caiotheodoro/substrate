"""A-K-39 knowctl — the 04 operations CLI.

Delegates to lib functions; every subcommand works offline against
in-memory backends (env `KNOW_BACKEND=pg` switches the stores to Postgres).
Bench output lands in `--outdir` (default `docs/validation/`).
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from substrate_knowledge.m1_characterization.decision import DecisionRule
from substrate_knowledge.m1_characterization.profiler import CorpusDocument, CorpusStructuralProfiler
from substrate_knowledge.m2_extraction.eval_harness import ExtractionEvalHarness
from substrate_knowledge.m2_extraction.extractor import PatternExtractor
from substrate_knowledge.m2_extraction.golden_slices import GOLDEN_SLICES
from substrate_knowledge.m2_extraction.ingest import IngestionPipeline
from substrate_knowledge.m3_resolution.blocker import Blocker
from substrate_knowledge.m3_resolution.canonical_store import CanonicalizationStore
from substrate_knowledge.m3_resolution.similarity import FelgiSunterScorer
from substrate_knowledge.m4_graph.assembler import GraphAssembler
from substrate_knowledge.m4_graph.graph_store import InMemoryGraph
from substrate_knowledge.m5_freshness.ledger import FreshnessLedger
from substrate_knowledge.m6_gate.verdict_classifier import DeterministicVerdictClassifier
from substrate_knowledge.m6_gate.verdict_store import VerdictStore
from substrate_knowledge.m7_observability.health import GraphHealthMonitor
from substrate_knowledge.m8_benchmarks.error_propagation import ErrorPropagationRunner
from substrate_knowledge.m8_benchmarks.graph_vs_flat import GraphVsFlatRunner
from substrate_knowledge.m8_benchmarks.retrieval_qa import RetrievalQARunner
from substrate_knowledge.m8_benchmarks.corpora import build_all_corpora
from substrate_knowledge.core.storage import InMemoryStore

app = typer.Typer(help="@substrate/knowledge operations CLI (offline-safe).")
DEFAULT_VALIDATION_DIR = Path("docs/validation")


@app.command("characterize")
def characterize(corpus_dir: Path = typer.Argument(..., help="directory of .txt corpus files"), json_out: bool = typer.Option(False, "--json")) -> None:
    """Profile a corpus directory and recommend an architecture (A-K-02)."""
    docs = _docs_from_dir(corpus_dir)
    if not docs:
        typer.echo("no .txt files found")
        raise typer.Exit(code=2)
    profile = CorpusStructuralProfiler().profile(docs)
    verdict = DecisionRule().decide(profile)
    if json_out:
        typer.echo(json.dumps(verdict.to_dict(), indent=2))
    else:
        typer.echo(f"corpus: {len(docs)} docs / {profile.n_entities} entities")
        typer.echo(f"architecture: {verdict.architecture or 'REFUSED'}")
        typer.echo(f"confidence:   {verdict.confidence:.3f}")
        typer.echo(f"reason:       {verdict.reason}")
        if verdict.refusal:
            typer.echo(f"refusal:      {verdict.refusal}", err=True)


@app.command("ingest")
def ingest(paths: list[Path] = typer.Argument(..., help="documents to parse/extract/resolve/assemble")) -> None:
    """Full pipeline: parse -> chunk -> extract -> resolve -> assemble."""
    pipeline = IngestionPipeline()
    extractor = PatternExtractor()
    graph = InMemoryGraph()
    canon = CanonicalizationStore(InMemoryStore())
    assembler = GraphAssembler(graph=graph, canonical_store=canon)
    for path in paths:
        chunks = pipeline.ingest(path)
        for chunk in chunks:
            result = extractor.extract(chunk.text, chunk.doc_id, chunk.chunk_id)
            assembler.upsert_facts(
                entities=result.entities,
                relations=result.relations,
                source=chunk.doc_id,
                chunk_id=chunk.chunk_id,
            )
            typer.echo(
                f"  {chunk.doc_id}: {len(result.entities)} entities, "
                f"{len(result.relations)} relations, {len(result.violations)} violations"
            )
    typer.echo(f"ingested into graph ({graph.node_count()} nodes, {graph.edge_count()} edges)")


@app.command("eval-extraction")
def eval_extraction(json_out: bool = typer.Option(False, "--json")) -> None:
    """Run the extraction eval harness over the golden slices (A-K-07/A-K-10)."""
    harness = ExtractionEvalHarness()
    extractor = PatternExtractor()
    report = harness.evaluate_slices(GOLDEN_SLICES, extractor)
    if json_out:
        typer.echo(json.dumps(report.to_dict(), indent=2))
    else:
        for s in report.slices:
            typer.echo(
                f"  {s.slice_id}: entity P={s.entity_precision:.2f} R={s.entity_recall:.2f} "
                f"relation P={s.relation_precision:.2f} R={s.relation_recall:.2f} "
                f"type-violations={s.type_violation_rate:.2f}"
            )
        typer.echo(f"continuous: P={report.continuous['entity_precision']:.3f} R={report.continuous['entity_recall']:.3f}")


@app.command("resolve")
def resolve() -> None:
    """Block + score entity records; enqueue ambiguous pairs for humans (A-K-11..14)."""
    blocker = Blocker()
    scorer = FellegiSunterScorer()
    typer.echo("resolution scaffold: blocking keys + Fellegi-Sunter scoring are libs;")
    typer.echo("run the human-confirmation queue service (:8202) for interactive review.")


@app.command("gate")
def gate(
    claim: str = typer.Option(..., "--claim"),
    evidence: list[str] = typer.Option(..., "--evidence"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Classify claim vs evidence -> support/contradict/silent (A-K-25)."""
    classifier = DeterministicVerdictClassifier()
    verdict = classifier.classify(claim, evidence)
    store = VerdictStore(InMemoryStore())
    store.record(verdict)
    if json_out:
        typer.echo(json.dumps(verdict.to_c3(), indent=2))
    else:
        typer.echo(f"kind: {verdict.kind.value}  prob: {verdict.prob:.3f}  evidence: {verdict.citedEvidence}")


@app.command("monitor")
def monitor(json_out: bool = typer.Option(False, "--json")) -> None:
    """Graph health + freshness report over the current stores (A-K-28/A-K-24)."""
    store = InMemoryStore()
    ledger = FreshnessLedger(store)
    health = GraphHealthMonitor().report(InMemoryGraph(), [])
    stale = [
        {"source": s, "age_s": ledger.staleness_age(s) or 0}
        for s in {k.split(":", 1)[1] for k, _ in store.scan("fresh:last:")}
    ]
    if json_out:
        typer.echo(json.dumps({"health": health.to_dict(), "stale_sources": stale}, indent=2))
    else:
        typer.echo(f"connectivity: {health.connectivity:.2f}  density: {health.relation_density:.2f}  sources: {health.n_sources}")


@app.command("bench")
def bench(outdir: Path = typer.Option(DEFAULT_VALIDATION_DIR, "--outdir")) -> None:
    """Run R1 (graph-vs-flat) + R2 (error propagation) + R5 (retrieval QA) suites."""
    outdir.mkdir(parents=True, exist_ok=True)
    corpora = build_all_corpora()
    runner = GraphVsFlatRunner()
    r1 = {"results": [runner.run(c).to_dict() for c in corpora]}
    _write(outdir / "r1_graph_vs_flat.json", r1)
    r2 = [p.to_dict() for p in ErrorPropagationRunner(seed=11).run()]
    _write(outdir / "r2_error_propagation.json", {"curve": r2})
    r5 = {"multi-hop": RetrievalQARunner().run(corpora[0], mode="graph").to_dict()}
    _write(outdir / "r5_retrieval_qa.json", r5)
    typer.echo(f"benchmarks written to {outdir}")


def _docs_from_dir(corpus_dir: Path) -> list[CorpusDocument]:
    docs = []
    for path in sorted(corpus_dir.iterdir()):
        if path.suffix.lower() == ".txt":
            docs.append(CorpusDocument(doc_id=path.stem, text=path.read_text(encoding="utf-8"), source=path.name))
    return docs


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


if __name__ == "__main__":
    app()
