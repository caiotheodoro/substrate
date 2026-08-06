"""A-S-33 — calibration corpus.

A small, bundled corpus of interaction transcripts (n=18) used to calibrate
latency/backchannel expectations. Versioned (v1) — a later sample can be
frozen at v2. All data is synthetic-but-shaped and shipped inside the package.
"""

from __future__ import annotations

import json
from pathlib import Path

CORPUS_PATH = Path(__file__).parent / "data" / "latency_corpus.json"
VERSION = "v1"


def load_latency_corpus() -> list[dict]:
    return json.loads(CORPUS_PATH.read_text())


class CalibrationCorpus:
    """Simple wrapper: version, entries, aggregate stats."""

    def __init__(self, version: str = VERSION):
        self.version = version
        self.entries = load_latency_corpus()

    @property
    def n(self) -> int:
        return len(self.entries)

    def stats(self) -> dict:
        gaps = [e["gap_rounds"] for e in self.entries]
        mean = sum(gaps) / len(gaps)
        gaps_sorted = sorted(gaps)
        p95 = gaps_sorted[int(0.95 * len(gaps_sorted)) - 1]
        return {"n": self.n, "mean_rounds": round(mean, 3), "p95_rounds": p95, "version": self.version}