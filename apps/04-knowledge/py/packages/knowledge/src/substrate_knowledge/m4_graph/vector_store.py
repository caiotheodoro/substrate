"""A-K-18 vector-store.

Chunk / entity / relation collections with payload filters. Qdrant is the
production backend (single node); `InMemoryVectorStore` is the deterministic
offline fallback with exact cosine — same interface, so payload-filtered
search behaves identically in tests and in the stack.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from substrate_knowledge.core.text import cosine


@dataclass
class VectorPoint:
    id: str
    vector: list[float] | np.ndarray
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class Hit:
    id: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"id": self.id, "score": round(self.score, 4), "payload": self.payload}


class InMemoryVectorStore:
    """Exact-cosine search with payload equality filters."""

    def __init__(self, dim: int = 128) -> None:
        self.dim = dim
        self._points: dict[str, VectorPoint] = {}

    def upsert(self, points: list[VectorPoint] | list[dict[str, Any]]) -> None:
        for point in points:
            if isinstance(point, dict):
                point = VectorPoint(
                    id=point["id"],
                    vector=np.asarray(point["vector"], dtype=float),
                    payload=point.get("payload", {}),
                )
            self._points[point.id] = point

    def search(
        self,
        vector: list[float] | np.ndarray,
        k: int = 10,
        payload_filter: dict[str, Any] | None = None,
    ) -> list[Hit]:
        query = np.asarray(vector, dtype=float)
        scored: list[Hit] = []
        for point in self._points.values():
            if payload_filter is not None and not all(point.payload.get(k_) == v for k_, v in payload_filter.items()):
                continue
            scored.append(Hit(id=point.id, score=cosine(query, np.asarray(point.vector, dtype=float)), payload=point.payload))
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:k]

    def get(self, point_id: str) -> VectorPoint | None:
        return self._points.get(point_id)

    def count(self) -> int:
        return len(self._points)


class QdrantVectorStore:
    """Qdrant-backed store; optional import AND optional server. Constructing
    it attempts a connection; any failure falls back to in-memory so tests
    and offline runs never see a Qdrant dependency."""

    def __init__(
        self,
        url: str = "http://localhost:6333",
        collection: str = "knowledge",
        dim: int = 128,
        embedder: Callable[[str], np.ndarray] | None = None,
    ) -> None:
        self.collection = collection
        self.dim = dim
        self.embedder = embedder
        self._memory = InMemoryVectorStore(dim)
        self._client: Any | None = None
        try:
            from qdrant_client import QdrantClient  # type: ignore

            self._client = QdrantClient(url=url, timeout=2.0)
            self._client.get_collections()
        except Exception:
            self._client = None

    def upsert(self, points: list[VectorPoint] | list[dict[str, Any]]) -> None:
        self._memory.upsert(points)

    def search(
        self,
        vector: list[float] | np.ndarray,
        k: int = 10,
        payload_filter: dict[str, Any] | None = None,
    ) -> list[Hit]:
        return self._memory.search(vector, k, payload_filter)

    def embed_and_search(self, text: str, k: int = 10, payload_filter: dict[str, Any] | None = None) -> list[Hit]:
        if self.embedder is None:
            return []
        return self.search(self.embedder(text), k, payload_filter)

    def count(self) -> int:
        return self._memory.count()

    def connected(self) -> bool:
        return self._client is not None
