"""A-S-12 baseline-arima: AutoARIMA via statsforecast + Gaussian ensemble CIs.

SimBench scores ensembles, so this baseline ships both a point/interval
forecast and an `as_ensemble` bootstrap sampler (point mean injected with
the residual scale) so a statistical arm enters the same ensemble-scoring
cross-reference as the simulators.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class AutoArimaForecaster:
    """Fits AutoARIMA to a monthly series; forecasts point + level intervals."""

    def __init__(self, horizon: int = 12, level: tuple[float, ...] = (0.5, 0.8, 0.95)):
        self.horizon = horizon
        self.level = level
        self._fc: dict | None = None
        self._sf = None
        self.residual_std: float = 0.0
        self._y = np.zeros(0)

    def fit(self, y: np.ndarray) -> "AutoArimaForecaster":
        from statsforecast import StatsForecast
        from statsforecast.models import AutoARIMA

        y = np.asarray(y, dtype=float)
        self._y = y
        series = pd.DataFrame(
            {"unique_id": "s", "ds": pd.date_range("2000-01-01", periods=len(y), freq="MS"), "y": y}
        )
        self._sf = StatsForecast(models=[AutoARIMA(season_length=12)], freq="MS", n_jobs=1)
        self._sf.fit(series)
        self.residual_std = float(np.std(np.diff(y))) / 2.0 + 1e-9
        return self

    def predict(self) -> dict:
        if self._sf is None:
            raise RuntimeError("fit() first")
        fc = self._sf.predict(h=self.horizon, level=[int(lev * 100) for lev in self.level])
        out = {"mean": fc["AutoARIMA"].values}
        for lev in self.level:
            tag = int(lev * 100)
            out[f"lo-{tag}"] = fc[f"AutoARIMA-lo-{tag}"].values
            out[f"hi-{tag}"] = fc[f"AutoARIMA-hi-{tag}"].values
        self._fc = out
        return out

    def as_ensemble(self, rng: np.random.Generator, n_members: int = 200) -> np.ndarray:
        """Bootstrapped members (n_members, horizon) from point + residual noise."""
        fc = self.predict() if self._fc is None else self._fc
        mean = fc["mean"]
        return mean[None, :] + rng.normal(0.0, self.residual_std, size=(n_members, self.horizon))