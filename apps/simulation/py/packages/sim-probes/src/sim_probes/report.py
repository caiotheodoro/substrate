"""A-S-34 — probe report. Collates A-S-31 + A-S-33 into a JSONL report
(pre-write JSON so it is a natural document)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .behavioral import ProbeResult
from .corpus import CalibrationCorpus


@dataclass
class ProbeReport:
    probes: Sequence[ProbeResult]
    corpus: CalibrationCorpus | None = None
    generated_at: str = ""

    def __post_init__(self) -> None:
        if not self.generated_at:
            self.generated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "version": "probe-report-v1",
            "generated_at": self.generated_at,
            "calibration": self.corpus.stats() if self.corpus else None,
            "probes": [asdict(p) for p in self.probes],
            "passed": sum(1 for p in self.probes if p.passed),
            "total": len(self.probes),
        }

    def write(self, path: Path) -> Path:
        path.write_text(json.dumps(self.to_dict(), indent=2))
        return path