"""Seeded RNG registry (A-S-18): every trajectory/run draws streams from a
named registry so a run is byte-reproducible from its seed alone."""

from __future__ import annotations

import hashlib

import numpy as np


class SeededRNG:
    """A named, seedable numpy Generator stream."""

    def __init__(self, seed: int, stream: str = "default"):
        self.seed = int(seed)
        self.stream = stream
        self.generator = np.random.default_rng(self._derive())

    def _derive(self) -> int:
        digest = hashlib.sha256(f"{self.seed}:{self.stream}".encode()).hexdigest()
        return int(digest[:16], 16)

    def next(self) -> np.random.Generator:
        return self.generator


class RNGRegistry:
    """Registry of named RNG streams for one run; `derive` spawns children.

    Every ensemble member gets a unique derived stream keyed by
    (run_seed, member_id) so member trajectories are independent but
    deterministic given the run seed.
    """

    def __init__(self, run_seed: int):
        self.run_seed = int(run_seed)
        self._streams: dict[str, SeededRNG] = {}

    def stream(self, name: str = "default") -> SeededRNG:
        if name not in self._streams:
            self._streams[name] = SeededRNG(self.run_seed, name)
        return self._streams[name]

    def derive(self, *parts: str | int) -> int:
        """Deterministic child seed for (run_seed, parts...)."""
        payload = f"{self.run_seed}:{':'.join(str(p) for p in parts)}"
        return int(hashlib.sha256(payload.encode()).hexdigest()[:16], 16)

    def generator(self, name: str = "default") -> np.random.Generator:
        return self.stream(name).next()
