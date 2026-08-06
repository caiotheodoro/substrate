"""Calibrators behind a protocol: netcal (Platt / isotonic) with a sklearn
fallback, so calibration is deterministic in tests and robust offline.
"""
from __future__ import annotations

from typing import Protocol

import numpy as np


class Calibrator(Protocol):
    def fit(self, confidence: np.ndarray, outcomes: np.ndarray) -> "Calibrator": ...
    def transform(self, confidence: np.ndarray) -> np.ndarray: ...
    def name(self) -> str: ...


class NetcalIsotonic:
    """netcal.binning.IsotonicRegression — deterministic."""

    kind = "netcal-isotonic"

    def __init__(self) -> None:
        from netcal.binning import IsotonicRegression

        self._cal = IsotonicRegression()

    def fit(self, confidence: np.ndarray, outcomes: np.ndarray) -> "NetcalIsotonic":
        self._cal.fit(np.asarray(confidence, dtype=float).reshape(-1, 1), np.asarray(outcomes, dtype=float))
        return self

    def transform(self, confidence: np.ndarray) -> np.ndarray:
        return self._cal.transform(np.asarray(confidence, dtype=float).reshape(-1, 1)).reshape(-1)

    def name(self) -> str:
        return self.kind


class NetcalPlatt:
    """netcal.scaling.LogisticCalibration (Platt). ``mean_estimate=True``
    keeps the transform deterministic."""

    kind = "netcal-platt"

    def __init__(self, random_state: int = 0) -> None:
        from netcal.scaling import LogisticCalibration

        self._cal = LogisticCalibration(random_state=random_state)
        self._random_state = random_state

    def fit(self, confidence: np.ndarray, outcomes: np.ndarray) -> "NetcalPlatt":
        self._cal.fit(np.asarray(confidence, dtype=float).reshape(-1, 1), np.asarray(outcomes, dtype=float))
        return self

    def transform(self, confidence: np.ndarray) -> np.ndarray:
        return self._cal.transform(
            np.asarray(confidence, dtype=float).reshape(-1, 1), mean_estimate=True, random_state=self._random_state
        ).reshape(-1)

    def name(self) -> str:
        return self.kind


class SklearnIsotonic:
    """Fallback when netcal is unavailable."""

    kind = "sklearn-isotonic"

    def __init__(self) -> None:
        from sklearn.isotonic import IsotonicRegression

        self._cal = IsotonicRegression(out_of_bounds="clip")

    def fit(self, confidence: np.ndarray, outcomes: np.ndarray) -> "SklearnIsotonic":
        self._cal.fit(np.asarray(confidence, dtype=float), np.asarray(outcomes, dtype=float))
        return self

    def transform(self, confidence: np.ndarray) -> np.ndarray:
        return np.asarray(self._cal.predict(np.asarray(confidence, dtype=float)), dtype=float)

    def name(self) -> str:
        return self.kind


def make_calibrator(kind: str = "isotonic") -> Calibrator:
    if kind == "platt":
        return NetcalPlatt()
    if kind == "isotonic":
        try:
            return NetcalIsotonic()
        except ImportError:
            return SklearnIsotonic()
    raise ValueError(f"unknown calibrator: {kind}")
