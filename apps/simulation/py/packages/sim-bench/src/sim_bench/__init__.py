"""A-S-01..05 simbench-core, runner, registry, report."""

from .scoring import (
    ScoreResult,
    brier_score,
    coverage,
    crps_ensemble,
    score_ensemble,
    tail_loss,
)
from .registry import AdapterRegistry
from .runner import DEFAULT_SHOCK_IDS, BenchMatrixRunner
from .report import build_report, write_report

__all__ = [
    "score_ensemble",
    "brier_score",
    "crps_ensemble",
    "tail_loss",
    "coverage",
    "ScoreResult",
    "AdapterRegistry",
    "BenchMatrixRunner",
    "DEFAULT_SHOCK_IDS",
    "build_report",
    "write_report",
]