"""A3 — evaluation-noise diagnostics (Airbnb Layer 1: name the noise).

Before interpreting any score movement, separate the two sources of
indeterminacy the article calls out:

1. **Reference regeneration rate** — how often LLM-generated references
   differ across runs on identical inputs (Airbnb measured ~75%). If the
   reference generator is unstable, a 2% score move may be reference
   shift, not model improvement.

2. **Judge drift** — how often the same judge changes its output on
   identical inputs across runs (Airbnb measured ~1%). Repeated sampling
   exposes judge-sensitive vs judge-stable samples; we never majority-vote
   (the eval cache is the fix), but the diagnostic measures the phenomenon.

Both axes feed `docs/validation/` artifacts and the A2 eval cache (stable
references/judges are cache-friendly; unstable ones are flagged).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from trust.confbench.eval_cache import canonical_json


def sample_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()[:16]


@dataclass
class NoiseReport:
    n_samples: int
    reference_regeneration_rate: float
    judge_drift_rate: float
    judge_sensitive_samples: list[str] = field(default_factory=list)
    judge_stable_samples: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_samples": self.n_samples,
            "reference_regeneration_rate": round(self.reference_regeneration_rate, 4),
            "judge_drift_rate": round(self.judge_drift_rate, 4),
            "n_judge_sensitive": len(self.judge_sensitive_samples),
            "n_judge_stable": len(self.judge_stable_samples),
            "diagnostics": self.diagnostics,
        }

    def write(self, path: str | Path) -> None:
        import json

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.as_dict(), indent=2))


@dataclass
class NoiseProbe:
    """One sample's two-run measurements."""

    sample_id: str
    ref_run_a: Any
    ref_run_b: Any
    judge_run_a: float
    judge_run_b: float

    @property
    def reference_regenerated(self) -> bool:
        return sample_hash(self.ref_run_a) != sample_hash(self.ref_run_b)

    @property
    def judge_drifted(self) -> bool:
        return self.judge_run_a != self.judge_run_b

    @property
    def judge_sensitive(self) -> bool:
        """High across-run judge variance: [0.45, 0.83] vs stable [0.78, 0.80]."""
        return abs(self.judge_run_a - self.judge_run_b) >= 0.2


def measure_noise(
    sample_ids: list[str],
    reference_generator: Callable[[str], Any],
    judge: Callable[[str, Any], float],
    *,
    regenerate_reference: bool = True,
    rerun_judge: bool = True,
) -> NoiseReport:
    """Run every sample through the reference generator twice and the judge
    twice, then report the two drift rates + judge-sensitive/stability split.

    ``regenerate_reference=False`` simulates a stable reference store (the
    A2 cache) — regeneration rate drops to zero by construction, which is
    the diagnostic's core message: cache the references, don't regenerate.
    """
    probes: list[NoiseProbe] = []
    for sid in sample_ids:
        ref_a = reference_generator(sid)
        ref_b = reference_generator(sid) if regenerate_reference else ref_a
        # Judge drift is measured on the SAME reference twice (only the
        # judge's own state varies); reference noise is measured separately.
        judge_a = judge(sid, ref_a)
        judge_b = judge(sid, ref_a) if rerun_judge else judge_a
        probes.append(NoiseProbe(sid, ref_a, ref_b, judge_a, judge_b))

    n = len(probes)
    ref_rate = sum(1 for p in probes if p.reference_regenerated) / n if n else 0.0
    judge_rate = sum(1 for p in probes if p.judge_drifted) / n if n else 0.0
    sensitive = [p.sample_id for p in probes if p.judge_sensitive]
    stable = [p.sample_id for p in probes if not p.judge_sensitive]
    return NoiseReport(
        n_samples=n,
        reference_regeneration_rate=ref_rate,
        judge_drift_rate=judge_rate,
        judge_sensitive_samples=sensitive,
        judge_stable_samples=stable,
        diagnostics={
            "regenerate_reference": regenerate_reference,
            "rerun_judge": rerun_judge,
        },
    )


class SeededNoisyReferenceGenerator:
    """A reference generator that regenerates a *different* string with
    probability ``noise_rate`` per sample — models Airbnb's ~75% reference
    regeneration. The noise decision is a seeded hash of the sample id, so
    a given sample deterministically either regenerates or is stable (the
    observed per-sample regeneration rate equals ``noise_rate``; a real
    LLM channel swaps in via the same callable shape)."""

    def __init__(self, seed: int = 7, noise_rate: float = 0.75) -> None:
        self.seed = seed
        self.noise_rate = noise_rate
        self._versions: dict[str, int] = {}

    def _draw(self, key: str) -> int:
        return int(hashlib.sha256(f"{self.seed}:{key}".encode("utf-8")).hexdigest()[:8], 16)

    def __call__(self, sample_id: str) -> str:
        noisy = (self._draw(sample_id) % 100) < self.noise_rate * 100
        version = self._versions.get(sample_id, 0)
        self._versions[sample_id] = version + 1
        if noisy:
            return f"ref-{sample_id}-{version}"
        return f"ref-{sample_id}-stable"


class SeededNoisyJudge:
    """A judge that scores the same (sample, reference) pair differently
    across runs with probability ``drift_rate`` (Airbnb ~1%; exaggerated in
    tests so the phenomenon is visible). The base score is a deterministic
    function of (sample, reference); drift only fires on the second run of
    a sample drawn from a seeded hash, so the same pair returns the same
    score unless the sample is a drifted one."""

    def __init__(self, seed: int = 11, drift_rate: float = 0.1, drift_magnitude: float = 0.3) -> None:
        self.seed = seed
        self.drift_rate = drift_rate
        self.drift_magnitude = drift_magnitude
        self._calls: dict[str, int] = {}

    def _draw(self, key: str) -> int:
        return int(hashlib.sha256(f"{self.seed}:{key}".encode("utf-8")).hexdigest()[:8], 16)

    def reset(self) -> None:
        """Clear per-sample run counters (start a fresh measurement)."""
        self._calls = {}

    def __call__(self, sample_id: str, reference: Any) -> float:
        base_draw = self._draw(f"{sample_id}:{sample_hash(reference)}")
        base = 0.3 + (base_draw % 40) / 100.0
        run = self._calls.get(sample_id, 0)
        self._calls[sample_id] = run + 1
        if run >= 1:
            drift_draw = self._draw(f"drift:{sample_id}")
            if (drift_draw % 100) < self.drift_rate * 100:
                base += self.drift_magnitude
        return round(min(max(base, 0.0), 1.0), 4)
