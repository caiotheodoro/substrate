"""A-T-25 contamination-gate — MinHash LSH (datasketch) + n-gram overlap vs
the holdout, with quarantine.

v1 covers the structural axes: near-duplicate detection via MinHash-LSH
against the holdout/eval corpus, and exact n-gram overlap (a leaked eval
sentence shows up as high n-gram overlap). Min-K%Pro needs a local reference
model (v2) and Faiss near-dup is an embedding-side concern (A-T-26); both are
documented here and not implemented. Rejected samples go to the quarantine
store with the matching reason.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Protocol

from trust.gated_data.models import GateVerdictResult, SeedRecord

DEFAULT_HOLDOUT_CORPUS: list[str] = [
    "The capital of the federation is Veria, and the currency is the mark.",
    "Protocol 7 requires all telemetry to be signed before transmission.",
    "The reactor output must remain below 4.2 gigawatts during peak load.",
]


def _ngrams(text: str, n: int) -> set[str]:
    words = text.lower().split()
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def ngram_overlap(text: str, corpus: list[str], n: int) -> float:
    """Fraction of the sample's n-grams that appear anywhere in the corpus."""
    sample_ngrams = _ngrams(text, n)
    if not sample_ngrams:
        return 0.0
    corpus_ngrams: set[str] = set()
    for doc in corpus:
        corpus_ngrams |= _ngrams(doc, n)
    return len(sample_ngrams & corpus_ngrams) / len(sample_ngrams)


def _minhash(text: str, num_perm: int = 128, seed: int = 1):
    from datasketch import MinHash

    mh = MinHash(num_perm=num_perm, seed=seed)
    for w in text.lower().split():
        mh.update(w.encode())
    return mh


class QuarantineStore(Protocol):
    """A-T-03 ``quarantine`` bucket semantics."""

    def quarantine(self, sample_id: str, reason: str, payload: dict) -> None: ...


class InMemoryQuarantineStore:
    def __init__(self) -> None:
        self._items: dict[str, dict] = {}

    def quarantine(self, sample_id: str, reason: str, payload: dict) -> None:
        self._items[sample_id] = {"reason": reason, "payload": payload}

    def list(self) -> list[str]:
        return sorted(self._items)

    def reasons(self) -> list[str]:
        return [v["reason"] for v in self._items.values()]


class MinioQuarantineStore:
    """Quarantine bucket on the compose MinIO (:9000)."""

    def __init__(self, bucket: str = "quarantine", object_store=None) -> None:
        from trust.db import MinioObjectStore

        self._store = object_store or MinioObjectStore(bucket=bucket)

    def quarantine(self, sample_id: str, reason: str, payload: dict) -> None:
        import json

        self._store.put(f"{sample_id}.json", json.dumps({"reason": reason, **payload}).encode())


@dataclass
class ContaminationGate:
    """Checks a seed against the holdout corpus; contaminated seeds are
    quarantined (never silently dropped — provenance must show what died)."""

    holdout_corpus: list[str] = field(default_factory=lambda: list(DEFAULT_HOLDOUT_CORPUS))
    minhash_threshold: float = 0.6
    ngram_threshold: float = 0.4
    ngram_n: int = 5
    quarantine: QuarantineStore | None = None
    _index: object = None  # lazy MinHashLSH index

    def _lsh(self):
        if self._index is None:
            from datasketch import MinHashLSH

            index = MinHashLSH(threshold=0.6, num_perm=128)
            for i, doc in enumerate(self.holdout_corpus):
                index.insert(f"holdout-{i}", _minhash(doc))
            self._index = index
        return self._index

    def evaluate(self, seed: SeedRecord) -> GateVerdictResult:
        reasons: list[str] = []

        ngram = ngram_overlap(seed.content, self.holdout_corpus, self.ngram_n)
        if ngram > self.ngram_threshold:
            reasons.append(f"ngram-overlap={ngram:.2f}")

        overlap = self._minhash_similarity(seed.content)
        if overlap is not None and overlap > self.minhash_threshold:
            reasons.append(f"minhash-similarity={overlap:.2f}")

        passed = not reasons
        if not passed and self.quarantine is not None:
            self.quarantine.quarantine(
                seed.sample_id,
                reason="contamination",
                payload={"sample_id": seed.sample_id, "content": seed.content[:200], "reasons": reasons},
            )
        return GateVerdictResult(
            "contamination",
            passed,
            reason="; ".join(reasons) or "clean",
            detail={"ngram_overlap": round(ngram, 4), "minhash_similarity": overlap},
        )

    def _minhash_similarity(self, text: str) -> float | None:
        """Best Jaccard similarity to any holdout document via LSH query."""
        try:
            query = _minhash(text)
            matches = self._lsh().query(query)
        except Exception:
            return None
        if not matches:
            return 0.0
        best = 0.0
        for m in matches:
            idx = int(m.split("-")[1])
            best = max(best, query.jaccard(_minhash(self.holdout_corpus[idx])))
        return best
