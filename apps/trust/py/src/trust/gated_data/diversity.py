"""A-T-26 diversity-steering — embeddings + clustering/coverage.

Embeddings come from the LLM backend protocol (Ollama ``nomic-embed-text``
in production, deterministic hash-vectors in tests). Clustering prefers
HDBSCAN when installed (ecosystem extra) and falls back to greedy
distance-threshold representatives otherwise; coverage is the ratio of
representative clusters to samples — low coverage = redundant corpus, which
is exactly what steering reports back to the generator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from trust.gated_data.models import GateVerdictResult, SeedRecord


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class StubEmbedder:
    """Deterministic offline embedding: hashed bag-of-words projection. Not a
    semantic model — a stable test double for the compose-time Ollama embedder."""

    kind = "stub"

    def __init__(self, dim: int = 32, seed: int = 0) -> None:
        self.dim = dim
        self._rng = np.random.RandomState(seed)

    def embed(self, texts: list[str]) -> list[list[float]]:
        import hashlib

        out: list[list[float]] = []
        for text in texts:
            vec = np.zeros(self.dim)
            for w in text.lower().split():
                # hashlib, not builtin hash() — Python's hash is salted per
                # process (PYTHONHASHSEED), which made embeddings and the
                # duplicate-content gate nondeterministic across runs.
                h = int(hashlib.md5(w.encode()).hexdigest()[:8], 16) % self.dim
                vec[h] += 1.0
            norm = np.linalg.norm(vec)
            out.append((vec / norm if norm > 0 else vec).tolist())
        return out


class OllamaEmbedder:
    """Ollama ``nomic-embed-text`` via the backend protocol."""

    kind = "ollama"

    def __init__(self, backend=None, base_url: str = "http://localhost:11434") -> None:
        from trust.model_backend import OllamaBackend

        self._backend = backend or OllamaBackend(base_url=base_url)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._backend.embeddings(texts)


@dataclass
class CoverageReport:
    n_samples: int
    n_representatives: int
    coverage: float
    clusters: list[int]

    def as_dict(self) -> dict[str, object]:
        return {
            "n_samples": self.n_samples,
            "n_representatives": self.n_representatives,
            "coverage": round(self.coverage, 4),
            "n_clusters": len(set(self.clusters)),
        }


def cluster_vectors(vectors: list[list[float]], *, distance_threshold: float = 0.3, seed: int = 0) -> tuple[list[int], CoverageReport]:
    """HDBSCAN when available, else greedy threshold clustering (fallback).

    Returns per-sample cluster labels plus a coverage report. The greedy
    fallback picks representatives in seed order and merges any vector within
    ``distance_threshold`` (cosine distance on normalized vectors)."""
    X = np.asarray(vectors, dtype=float)
    if len(X) == 0:
        return [], CoverageReport(0, 0, 0.0, [])
    try:
        import hdbscan  # type: ignore

        clusterer = hdbscan.HDBSCAN(min_cluster_size=2, metric="euclidean")
        labels = [int(c) for c in clusterer.fit_predict(X)]
    except (ImportError, ValueError):  # pragma: no cover - fallback path
        labels = _greedy_labels(X, distance_threshold, seed)
    n_repr = len(set(labels))
    return labels, CoverageReport(n_samples=len(X), n_representatives=n_repr, coverage=n_repr / len(X), clusters=labels)


def _greedy_labels(X: np.ndarray, threshold: float, seed: int) -> list[int]:
    labels: list[int] = []
    representatives: list[tuple[int, np.ndarray]] = []
    order = list(range(len(X)))
    rng = np.random.RandomState(seed)
    rng.shuffle(order)
    for idx in order:
        x = X[idx]
        assigned = None
        for cid, rep in representatives:
            if _cosine_distance(x, rep) <= threshold:
                assigned = cid
                break
        if assigned is None:
            assigned = len(representatives)
            representatives.append((assigned, x))
        labels.append(assigned)
    by_index = {idx: cid for idx, cid in zip(order, labels)}
    return [by_index[i] for i in range(len(X))]


def _cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(1.0 - np.dot(a, b) / (na * nb))


class DiversityGate:
    """Coverage steering: reject redundant samples when coverage would stay
    unchanged (i.e. the sample is within threshold of an existing cluster)."""

    def __init__(self, embedder: Embedder | None = None, distance_threshold: float = 0.3, seed: int = 0) -> None:
        self.embedder = embedder or StubEmbedder()
        self.distance_threshold = distance_threshold
        self.seed = seed
        self._accepted_vectors: list[list[float]] = []
        self._accepted_ids: list[str] = []

    def evaluate(self, seed_record: SeedRecord) -> GateVerdictResult:
        vec = self.embedder.embed([seed_record.content])[0]
        redundant = any(_cosine_distance(np.asarray(vec), np.asarray(v)) <= self.distance_threshold for v in self._accepted_vectors)
        if redundant:
            return GateVerdictResult("diversity", False, "redundant", {"distance_threshold": self.distance_threshold})
        self._accepted_vectors.append(vec)
        self._accepted_ids.append(seed_record.sample_id)
        return GateVerdictResult("diversity", True, "adds coverage", {"n_accepted": len(self._accepted_vectors)})

    def coverage(self) -> CoverageReport:
        labels, report = cluster_vectors(self._accepted_vectors, distance_threshold=self.distance_threshold, seed=self.seed)
        return report
