from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WorldClock:
    """Shared simulation clock; ticks discrete rounds."""

    t: int = 0

    def tick(self, n: int = 1) -> int:
        self.t += n
        return self.t

    def now(self) -> str:
        return f"t={self.t}"