"""A-S-14 baseline-hub: ForecastAdapter + lookahead-free backtest.

Retro-validation integrity (BUILD rule 1): a baseline backtest NEVER reads data
after its scoring horizon. `backtest_lookahead_free` trains each adapter only on
the point-in-time slice `dataset.load(series, as_of=...)`. When fred-ingest
supplies ALFRED vintages, the same as-of truncation is vintage-driven.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

import numpy as np
import pandas as pd

from sim_datasets import ShockDataset, require_calibration_ok


@dataclass
class BaselineForecast:
    method: str
    as_of: str
    series_id: str
    horizon: int
    point: np.ndarray
    intervals: dict[float, tuple[np.ndarray, np.ndarray]]
    ensemble: np.ndarray | None = None
    meta: dict = field(default_factory=dict)


class ForecastAdapter(Protocol):
    method: str

    def fit(self, y: np.ndarray) -> "ForecastAdapter": ...

    def forecast(
        self, horizon: int, rng: np.random.Generator, series_id: str = "", as_of: str = ""
    ) -> BaselineForecast: ...


class ForecastAdapterTrainingError(RuntimeError):
    pass


@dataclass
class ForecastRecord:
    as_of: str
    series_id: str
    realized: np.ndarray
    forecast: BaselineForecast


def _series_asof_position(dataset: ShockDataset, series_id: str, as_of: str) -> int:
    """Index of the first realized observation STRICTLY AFTER `as_of`."""
    realized_dates = dataset.realized_path(series=[series_id])["date"].sort_values()
    ts = pd.Timestamp(as_of)
    pos = realized_dates[realized_dates > ts]
    if pos.empty:
        raise ValueError(f"{as_of} is past the end of {series_id}'s realized path")
    return int(realized_dates.index[pos.index])  # absolute position in full frame


def backtest_lookahead_free(
    dataset: ShockDataset,
    series_id: str,
    adapter_factory: Callable[[], ForecastAdapter],
    scoring_as_of: list[str],
    horizon: int,
    rng: np.random.Generator,
) -> list[ForecastRecord]:
    """One forecast per `scoring_as_of`, trained on the pre-`as_of` slice.

    Raises HoldoutError for the 2025 tariff wave — the end-to-end holdout is
    never a calibration/backtest participant.
    """
    require_calibration_ok(dataset.id)

    realized_df = dataset.realized_path(series=[series_id]).sort_values("date")
    realized_vals = realized_df["value"].to_numpy(dtype=float)
    realized_dates = realized_df["date"].tolist()

    records: list[ForecastRecord] = []
    for k, as_of in enumerate(scoring_as_of):
        train = dataset.load(series=[series_id], as_of=as_of)
        y = train["value"].to_numpy(dtype=float)
        if len(y) < 12:
            raise ForecastAdapterTrainingError(f"{series_id}: only {len(y)} obs as of {as_of}")
        adapter = adapter_factory().fit(y)
        fc = adapter.forecast(horizon=horizon, rng=rng, series_id=series_id, as_of=as_of)

        asof_ts = pd.Timestamp(as_of)
        next_dates = [d for d in realized_dates if d > asof_ts]
        if not next_dates:
            raise ValueError(f"no realized data after {as_of}")
        window = np.array(
            [realized_vals[i] for i, d in enumerate(realized_dates) if d in next_dates[:horizon]],
            dtype=float,
        )
        records.append(
            ForecastRecord(as_of=as_of, series_id=series_id, realized=window, forecast=fc)
        )
    return records