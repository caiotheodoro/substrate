"""M3 — entity resolution: blocking, scoring, calibration, human queue."""

from substrate_knowledge.m3_resolution.blocker import Blocker, Block, EntityRecord, canonical_name
from substrate_knowledge.m3_resolution.calibrator import CalibrationBand, ResolutionCalibrator
from substrate_knowledge.m3_resolution.canonical_store import CanonicalizationStore
from substrate_knowledge.m3_resolution.human_queue import HumanConfirmationQueue, QueueItem
from substrate_knowledge.m3_resolution.similarity import (
    DEFAULT_M_PROBS,
    DEFAULT_U_PROBS,
    FelgiSunterScorer,
    PairScore,
)

__all__ = [
    "Blocker",
    "Block",
    "EntityRecord",
    "canonical_name",
    "CalibrationBand",
    "ResolutionCalibrator",
    "CanonicalizationStore",
    "HumanConfirmationQueue",
    "QueueItem",
    "FelgiSunterScorer",
    "PairScore",
    "DEFAULT_M_PROBS",
    "DEFAULT_U_PROBS",
]
