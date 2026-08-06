"""A-S-06..09 datasets + the calibration/holdout guard.

Every ShockDataset ships its realized path (`realized_path`) alongside
placeholder vintage metadata (`vintages`) that documents the point-in-time
discipline fred-ingest will enforce. `require_calibration_ok` is the
single choke point for the 2025 HOLDOUT rule.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent / "data"

HOLDOUT_IDS = frozenset({"shock-2025-tariff", "tariffs-2025"})


class HoldoutError(RuntimeError):
    """Raised when calibration touches the 2025 tariff wave. Ever."""


def require_calibration_ok(shock_ids: str | Iterable[str]) -> None:
    """Refuse any calibration path that includes the 2025 HOLDOUT."""
    ids = [shock_ids] if isinstance(shock_ids, str) else list(shock_ids)
    for sid in ids:
        clean = sid.rsplit("/", 1)[-1].replace(".parquet", "")
        if clean in HOLDOUT_IDS:
            raise HoldoutError(
                f"calibration path rejected: `{sid}` is the end-to-end 2025 HOLDOUT "
                "— seed/calibrate/backtest against it is forbidden (BUILD.md integrity rule 2)"
            )


@dataclass
class ShockDataset:
    id: str
    name: str
    window: str
    holdout: bool
    series: list[str]
    support: tuple[str, str]
    scenario_id: str
    data_path: Path

    # --- loading -----------------------------------------------------------
    def load(self, series: Iterable[str] | None = None, as_of: str | None = None) -> pd.DataFrame:
        """Monthly long-format `date, series_id, value, quality`.

        `as_of` = point-in-time date: rows with `date > as_of` are dropped,
        giving a lookahead-free snapshot for baseline backtesting.
        """
        frames = []
        for sid in self.series:
            if series is not None and sid not in set(series):
                continue
            path = self.data_path / f"{sid}.csv"
            df = pd.read_csv(path, parse_dates=["date"])
            frames.append(df)
        out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
            columns=["date", "series_id", "value", "quality"]
        )
        if as_of is not None:
            as_of_ts = pd.Timestamp(as_of)
            out = out[out["date"] <= as_of_ts]
        return out

    def realized_path(self, series: Iterable[str] | None = None) -> pd.DataFrame:
        """Full realized path (unconstrained by any vintage) — scoring only."""
        return self.load(series)

    def vintages(self) -> list[dict]:
        """Placeholder ALFRED vintage metadata (replaced by fred-ingest).

        A `null` vintage after the series' latest revised release means the
        value is *current-rate*; retro paths must come from ALFRED snapshots.
        """
        return [
            {
                "series": sid,
                "shock_id": self.id,
                "source": "fred-alfred",
                "placeholder": True,
                "first_known": self._first_observation(sid),
                "revision_policy": "point-in-time (ALFRED vintage at decision date)",
                "note": "hand-curated starter; replaced by fred-ingest (A-S-10)",
            }
            for sid in self.series
        ]

    def _first_observation(self, sid: str) -> str | None:
        df = pd.read_csv(self.data_path / f"{sid}.csv")
        if df.empty:
            return None
        return str(df["date"].iloc[0])

    def to_parquet(self, out_dir: Path | str) -> Path:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        df = self.load()
        path = out_dir / f"{self.id}.parquet"
        df.to_parquet(path, index=False)
        return path

    def to_duckdb(self, con, table: str = "shock_series") -> None:
        con.register("__df", self.load())
        con.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM __df")
        con.unregister("__df")


def _read_metadata(shock_dir: Path) -> dict | None:
    meta_path = shock_dir / "metadata.json"
    if not meta_path.exists():
        return None
    return json.loads(meta_path.read_text())


def _discover() -> list[ShockDataset]:
    datasets = []
    for shock_dir in sorted(DATA_DIR.iterdir()):
        if not shock_dir.is_dir():
            continue
        meta = _read_metadata(shock_dir)
        if not meta:
            continue
        datasets.append(
            ShockDataset(
                id=meta["id"],
                name=meta["name"],
                window=meta["window"],
                holdout=bool(meta.get("holdout", False)),
                series=list(meta["series"]),
                support=tuple(meta["support"]),
                scenario_id=meta["scenario_id"],
                data_path=shock_dir,
            )
        )
    return datasets


_DATASETS: list[ShockDataset] | None = None


def available_shocks() -> list[str]:
    global _DATASETS
    if _DATASETS is None:
        _DATASETS = _discover()
    return [d.id for d in _DATASETS]


def get_dataset(shock_id: str) -> ShockDataset:
    global _DATASETS
    if _DATASETS is None:
        _DATASETS = _discover()
    if shock_id not in HOLDOUT_IDS and shock_id not in [d.id for d in _DATASETS]:
        raise KeyError(f"unknown shock dataset: {shock_id}")
    aliases = {d.id: d for d in _DATASETS}
    # tolerate scenario-level id (tariffs-2025) mapping to dataset id
    for d in _DATASETS:
        if d.scenario_id == shock_id:
            return d
    return aliases[shock_id]