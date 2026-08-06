"""Deterministic per-sample eval cache — the Layer-2 foundation.

Airbnb's "deterministic evaluation foundation": evaluation becomes
reproducible by caching on both axes instead of modeling around judge
instability —

  references / model outputs  keyed by (sample_id, config)
  judge scores                keyed by (sample_id, model_output, judge_config, metric)

Identical inputs return cached results; no majority-voting (sampling
converges to the judge's central tendency, not accuracy — the anti-pattern
Layer 2 exists to avoid). Experiment-level keying makes partial progress
durable: a run failing at sample N resumes from the cache, and each new
candidate/metric reuses cached outputs for free.

The cache is a pure key→value store with canonical-JSON+SHA-256 keys (the
same keying family as 03's prompt-fingerprinter), backed by a JSONL file or
in-memory for tests. Write-through on miss; never overwrites a hit.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


def canonical_json(value: Any) -> str:
    """Byte-stable JSON regardless of key order (mirrors canonicalJson)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def cache_key(*parts: Any) -> str:
    """SHA-256 of the canonical concatenation of the key parts."""
    payload = "|".join(canonical_json(p) for p in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class EvalCache:
    """Deterministic per-sample cache.

    ``get(key)`` returns the cached value or None; ``put(key, value)`` is
    write-through and never overwrites an existing entry (a key collision
    with different content is an error — it would hide a config bug).
    """

    def __init__(self, path: Path | None = None) -> None:
        self._entries: dict[str, Any] = {}
        self.hits = 0
        self.misses = 0
        if path is not None:
            self._load(path)
        self._path = path

    def _load(self, path: Path) -> None:
        if not path.exists():
            return
        for line in path.read_text("utf8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            self._entries[row["key"]] = row["value"]

    def get(self, key: str) -> Any | None:
        if key in self._entries:
            self.hits += 1
            return self._entries[key]
        self.misses += 1
        return None

    def put(self, key: str, value: Any) -> None:
        if key in self._entries:
            if canonical_json(self._entries[key]) != canonical_json(value):
                raise ValueError(f"cache key collision with different content: {key}")
            return
        self._entries[key] = value
        if self._path is not None:
            self._flush(key, value)

    def _flush(self, key: str, value: Any) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf8") as fh:
            fh.write(json.dumps({"key": key, "value": value}) + "\n")

    def persist(self, path: Path) -> None:
        """Write the full cache atomically (temp file + rename)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf8") as fh:
                for key, value in self._entries.items():
                    fh.write(json.dumps({"key": key, "value": value}) + "\n")
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    @property
    def size(self) -> int:
        return len(self._entries)

    def stats(self) -> dict[str, int]:
        return {"entries": self.size, "hits": self.hits, "misses": self.misses}


@dataclass(frozen=True)
class CachedEval:
    """The two caching axes, memoized:

    - references/model outputs per (sample_id, config)
    - judge scores per (sample_id, model_output, judge_config, metric)

    ``compute`` runs only on a cache miss; ``same_outputs`` proves the
    determinism property (identical inputs → identical cached outputs).
    """

    cache: EvalCache = field(default_factory=EvalCache)

    def reference(self, sample_id: str, config: dict[str, Any], compute: Callable[[], Any]) -> Any:
        key = cache_key("ref", sample_id, config)
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        value = compute()
        self.cache.put(key, value)
        return value

    def judge_score(
        self,
        sample_id: str,
        model_output: Any,
        judge_config: dict[str, Any],
        metric: str,
        compute: Callable[[], Any],
    ) -> Any:
        key = cache_key("judge", sample_id, model_output, judge_config, metric)
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        value = compute()
        self.cache.put(key, value)
        return value

    def same_outputs(self, a: Any, b: Any) -> bool:
        """Determinism property: identical inputs produce identical cached bytes."""
        return canonical_json(a) == canonical_json(b)


def cache_baseline_scores(
    cache: EvalCache,
    baseline_name: str,
    task_ids: list[str],
    compute: Callable[[], list[float]],
) -> list[float]:
    """Per-sample memoization of a baseline's score list.

    Keyed ``(baseline_name, task_id)`` so a rerun of ConfBench with the same
    tasks serves every baseline score from cache — identical inputs return
    identical cached outputs (the Layer-2 determinism property), and a run
    that dies midway resumes without recomputing finished samples.
    """
    scores: list[float] = []
    for i, task_id in enumerate(task_ids):
        key = cache_key("baseline", baseline_name, task_id)
        hit = cache.get(key)
        if hit is not None:
            scores.append(float(hit))
            continue
        row = compute()
        value = float(row[i])
        cache.put(key, value)
        scores.append(value)
    return scores
