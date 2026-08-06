"""A-K-13 resolution-calibrator — precision at ambiguity bands (R4).

Entity-resolution quality measured like calibration: candidate merge pairs
are binned by fused score, and each band reports precision (fraction of
pairs that are true matches). The human-confirmation threshold is then the
lowest band that holds the target precision — a designed decision, not a
guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from substrate_knowledge.m3_resolution.similarity import PairScore


@dataclass
class CalibrationBand:
    lower: float
    upper: float
    precision: float
    n_pairs: int
    n_matches: int

    def to_dict(self) -> dict:
        return {
            "band": f"[{self.lower:.3f}, {self.upper:.3f})",
            "precision": round(self.precision, 4),
            "n_pairs": self.n_pairs,
            "n_matches": self.n_matches,
        }


@dataclass
class CalibrationResult:
    bands: list[CalibrationBand] = field(default_factory=list)
    target_precision: float = 0.95
    queue_threshold: float | None = None

    def to_dict(self) -> dict:
        return {
            "bands": [b.to_dict() for b in self.bands],
            "target_precision": self.target_precision,
            "queue_threshold": round(self.queue_threshold, 4) if self.queue_threshold is not None else None,
        }


class ResolutionCalibrator:
    def __init__(self, n_bands: int = 10, target_precision: float = 0.95) -> None:
        self.n_bands = n_bands
        self.target_precision = target_precision

    def calibrate(self, scored_pairs: list[tuple[PairScore, bool]], n_bands: int | None = None) -> CalibrationResult:
        """`scored_pairs`: (pair, is_true_match). Returns bands and the queue
        threshold: the lowest score that still holds target precision."""
        n_bands = n_bands or self.n_bands
        if not scored_pairs:
            return CalibrationResult(target_precision=self.target_precision)
        lo = min(p.fused_score for p, _ in scored_pairs)
        hi = max(p.fused_score for p, _ in scored_pairs)
        width = (hi - lo) / n_bands or 1.0
        bins: list[dict] = [{"matches": 0, "n": 0} for _ in range(n_bands)]
        for pair, is_match in scored_pairs:
            idx = min(int((pair.fused_score - lo) / width), n_bands - 1)
            bins[idx]["matches"] += int(is_match)
            bins[idx]["n"] += 1
        bands = []
        for i, bin_ in enumerate(bins):
            lower = lo + i * width
            upper = lo + (i + 1) * width
            n = bin_["n"]
            precision = bin_["matches"] / n if n else 0.0
            bands.append(CalibrationBand(lower, upper, precision, n, bin_["matches"]))
        bands.sort(key=lambda b: b.lower, reverse=True)

        threshold: float | None = None
        for band in bands:
            if band.n_pairs > 0 and band.precision >= self.target_precision:
                threshold = band.lower
                break
        return CalibrationResult(bands=bands, target_precision=self.target_precision, queue_threshold=threshold)

    def recommend_threshold(self, scored_pairs: list[tuple[PairScore, bool]]) -> float | None:
        return self.calibrate(scored_pairs).queue_threshold
