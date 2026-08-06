"""A-T-28 gated-dataset-lib — ``gate(seeds, policy) -> Dataset``.

The reusable deliverable: seeds from any world source run the four gates
(verifiability, label quality, contamination, diversity) in a fixed order;
every pass/fail decision is stamped into the sample's provenance; rejected
samples are quarantined when the policy says so; the result is a versioned
``Dataset`` with a summary manifest.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from trust.gated_data.contamination import ContaminationGate, InMemoryQuarantineStore, QuarantineStore
from trust.gated_data.diversity import DiversityGate, Embedder, StubEmbedder
from trust.gated_data.label_quality import LabelQualityGate, Reviewer
from trust.gated_data.models import (
    Dataset,
    DatasetSummary,
    GatedSample,
    GatePolicy,
    GateVerdictResult,
    SeedRecord,
)
from trust.gated_data.provenance import InMemoryProvenanceTracker, ProvenanceRecord
from trust.gated_data.verifiability import VerifiabilityGate

GATE_ORDER = ("verifiability", "label_quality", "contamination", "diversity")


@dataclass
class GatedRun:
    """Every gate verdict for every seed — the audit trail behind a Dataset."""

    verdicts: dict[str, list[GateVerdictResult]] = field(default_factory=dict)
    provenance: dict[str, ProvenanceRecord] = field(default_factory=dict)
    quarantine: InMemoryQuarantineStore | None = None


def gate(
    seeds: list[SeedRecord],
    policy: GatePolicy | None = None,
    *,
    reviewer: Reviewer | None = None,
    embedder: Embedder | None = None,
    holdout_corpus: list[str] | None = None,
    quarantine: QuarantineStore | None = None,
    provenance: InMemoryProvenanceTracker | None = None,
    version: str | None = None,
    seed: int = 42,
) -> tuple[Dataset, GatedRun]:
    """Run the full gate chain over seeds. Returns (Dataset, GatedRun); the
    run record carries the full audit trail (every verdict + quarantine)."""
    policy = policy or GatePolicy()
    tracker = provenance or InMemoryProvenanceTracker()
    quarantine_store = quarantine or (InMemoryQuarantineStore() if policy.quarantine_contaminated else None)
    run = GatedRun(quarantine=quarantine_store if isinstance(quarantine_store, InMemoryQuarantineStore) else None)

    gates: dict[str, Any] = {}
    if policy.verifiability:
        gates["verifiability"] = VerifiabilityGate(policy.require_checkable, policy.require_verified)
    if policy.label_quality:
        gates["label_quality"] = LabelQualityGate(policy.label_sample_rate, reviewer=reviewer, seed=seed)
    if policy.contamination:
        cont_kwargs = dict(
            minhash_threshold=policy.minhash_threshold,
            ngram_threshold=policy.ngram_threshold,
            ngram_n=policy.ngram_n,
            quarantine=quarantine_store,
        )
        if holdout_corpus is not None:
            cont_kwargs["holdout_corpus"] = holdout_corpus
        gates["contamination"] = ContaminationGate(**cont_kwargs)
    if policy.diversity:
        gates["diversity"] = DiversityGate(embedder=embedder or StubEmbedder(seed=seed), distance_threshold=policy.diversity_distance_threshold, seed=seed)

    accepted: list[GatedSample] = []
    rejected_by_gate: dict[str, int] = {}
    quarantine_reasons: list[str] = []

    for s in seeds:
        record = tracker.record(s.sample_id)
        record.source = s.source
        record.world = s.world
        record.seed_id = s.sample_id
        record.add("ingest", {"content_sha256": _sha256(s.content)})

        verdicts: list[GateVerdictResult] = []
        sample_accepted = True
        for gate_name in GATE_ORDER:
            if gate_name not in gates:
                continue
            verdict = gates[gate_name].evaluate(s)
            verdicts.append(verdict)
            record.add(gate_name, {"passed": verdict.passed, "reason": verdict.reason, **verdict.detail})
            if not verdict.passed:
                sample_accepted = False
                rejected_by_gate[gate_name] = rejected_by_gate.get(gate_name, 0) + 1
                if gate_name == "contamination" and quarantine_store is not None:
                    quarantine_reasons.append(verdict.gate)
                break

        run.verdicts[s.sample_id] = verdicts
        if sample_accepted:
            accepted.append(GatedSample(sample_id=s.sample_id, content=s.content, label=s.label, provenance=record, gate_results=verdicts))

    dataset_version = version or f"v1-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    for rec in tracker.all():
        rec.dataset_version = dataset_version

    coverage = 0.0
    if isinstance(gates.get("diversity"), DiversityGate):
        coverage = gates["diversity"].coverage().coverage

    summary = DatasetSummary(
        total=len(seeds),
        accepted=len(accepted),
        rejected=len(seeds) - len(accepted),
        rejected_by_gate=rejected_by_gate,
        diversity_coverage=coverage,
        version=dataset_version,
    )
    if quarantine_reasons:
        from collections import Counter

        summary.quarantine_reasons = Counter(quarantine_reasons)
    dataset = Dataset(version=dataset_version, samples=accepted, provenance={rec.sample_id: rec for rec in tracker.all()}, summary=summary)
    return dataset, run


def _sha256(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode()).hexdigest()


def _cli_main() -> None:
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(prog="trust-gate-data", description="A-T-28: run the gate chain over seeds")
    parser.add_argument("--in", dest="in_path", required=True, help="jsonl of SeedRecord dicts")
    parser.add_argument("--out", dest="out_path", required=True, help="jsonl output for the accepted dataset")
    args = parser.parse_args()
    from trust.gated_data.ingest import StaticWorldSeedSource

    seeds = StaticWorldSeedSource(path=args.in_path).fetch_seeds()
    dataset, run = gate(seeds, GatePolicy())
    dataset.to_jsonl(args.out_path)
    print(json.dumps(dataset.summary.as_dict(), indent=2))


if __name__ == "__main__":
    _cli_main()
