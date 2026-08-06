"""ForecastAdapter implementations wrapping the two baseline arms (A-S-12/13)
into the hub contract (A-S-14)."""

from __future__ import annotations

import numpy as np

from .arima import AutoArimaForecaster
from .hub import BaselineForecast, ForecastAdapter
from .lightgbm import LightGBMQuantileForecaster

INTERVAL_LEVELS = (0.5, 0.8, 0.95)


class ArimaAdapter:
    method = "auto-arima"

    def __init__(self, horizon: int = 12, ensemble_members: int = 200):
        self.horizon = horizon
        self.ensemble_members = ensemble_members
        self._model = AutoArimaForecaster(horizon=horizon, level=INTERVAL_LEVELS)

    def fit(self, y: np.ndarray) -> "ArimaAdapter":
        self._model.fit(y)
        return self

    def forecast(
        self, horizon: int, rng: np.random.Generator, series_id: str = "", as_of: str = ""
    ) -> BaselineForecast:
        fc = self._model.predict()
        intervals = {
            lev: (fc[f"lo-{int(lev * 100)}"], fc[f"hi-{int(lev * 100)}"])
            for lev in INTERVAL_LEVELS
        }
        ensemble = self._model.as_ensemble(rng, n_members=self.ensemble_members)
        return BaselineForecast(
            method=self.method,
            as_of=as_of,
            series_id=series_id,
            horizon=horizon,
            point=fc["mean"],
            intervals=intervals,
            ensemble=ensemble,
            meta={"residual_std": self._model.residual_std},
        )


class LightGBMAdapter:
    method = "lightgbm-quantile"

    def __init__(self, horizon: int = 12, ensemble_members: int = 200, seed: int = 0, conformal: bool = True):
        self.horizon = horizon
        self.ensemble_members = ensemble_members
        self.seed = seed
        self.conformal = conformal
        self._model = None
        self._last_y = 0.0

    def fit(self, y: np.ndarray) -> "LightGBMAdapter":
        self._last_y = float(np.asarray(y)[-1])
        self._model = LightGBMQuantileForecaster(
            horizon=self.horizon, seed=self.seed, conformal=self.conformal
        ).fit(np.asarray(y))
        return self

    def forecast(
        self, horizon: int, rng: np.random.Generator, series_id: str = "", as_of: str = ""
    ) -> BaselineForecast:
        if self._model is None:
            raise RuntimeError("fit() first")
        fc = self._model.predict(self._last_y, rng)
        intervals = {
            0.5: (fc["q20"], fc["q80"]),
            0.8: (fc["q10"], fc["q90"]),
            0.95: (fc["q05"], fc["q95"]),
        }
        ensemble = self._model.as_ensemble(self._last_y, rng, n_members=self.ensemble_members)
        return BaselineForecast(
            method=self.method,
            as_of=as_of,
            series_id=series_id,
            horizon=horizon,
            point=fc["mean"],
            intervals=intervals,
            ensemble=ensemble,
            meta={"conformal": self.conformal},
        )