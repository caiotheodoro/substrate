"""Shared text primitives: tokenization, n-grams, hashing-trick embeddings.

The hashing embedder gives real cosine semantics (token-overlap similarity)
with zero model dependencies, so every downstream consumer (blocker, drift,
subgraph, round-trip) is testable offline while remaining swappable for a
real embedding model via the LLM provider abstraction.
"""

from __future__ import annotations

import hashlib
import math
import re

import numpy as np

_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
_STOPWORDS = frozenset(
    """
    a an the and or but if then else for of to in on at by with from as is are was were be been
    has have had do does did will would can could should may might this that these those it its
    their our your my his her not no nor so such than too very just about into over under after
    before between during above below we you they them he she i
    """.split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


def ngrams(tokens: list[str], n: int = 2) -> set[tuple[str, ...]]:
    return {tuple(tokens[i : i + n]) for i in range(max(0, len(tokens) - n + 1))}


def term_frequency(tokens: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for t in tokens:
        counts[t] = counts.get(t, 0) + 1
    return counts


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def _hash_index(token: str, dim: int, seed: int) -> tuple[int, float]:
    digest = hashlib.md5(f"{seed}:{token}".encode("utf-8")).hexdigest()
    h = int(digest[:8], 16)
    return h % dim, (1.0 if (h >> 8) % 2 == 0 else -1.0)


def hash_embed(text: str, dim: int = 128, seed: int = 7) -> np.ndarray:
    """Deterministic bag-of-words hashing embedding, L2-normalized."""
    vec = np.zeros(dim, dtype=np.float64)
    for token in tokenize(text):
        idx, sign = _hash_index(token, dim, seed)
        vec[idx] += sign
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.clip(float(np.dot(a, b) / denom), -1.0, 1.0))


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def safe_div(a: float, b: float) -> float:
    return a / b if b > 0 else 0.0
