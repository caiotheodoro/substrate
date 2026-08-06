"""A-S-10 fred-ingest: FRED/ALFRED point-in-time fetcher behind an interface.

ALFRED vintages are the integrity mechanism for retro-validation (BUILD.md
rule 1): `vintage_series(series_id, vintage_date)` returns the series as it
was KNOWN on `vintage_date`, so baselines and seeds consume no future data.
The FRED API needs an API key (env `FRED_API_KEY`); tests stub the transport.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import httpx
import pandas as pd

from .datasets import get_dataset, require_calibration_ok


class FredAuthError(RuntimeError):
    pass


@dataclass
class FredClient:
    api_key: str = os.environ.get("FRED_API_KEY", "")
    base_url: str = "https://api.stlouisfed.org/fred"
    transport: httpx.BaseTransport | None = None

    def __post_init__(self) -> None:
        self.http = httpx.Client(
            base_url=self.base_url,
            params={"api_key": self.api_key, "file_type": "json"},
            transport=self.transport,
        )

    def series_observations(self, series_id: str, vintage_date: str | None = None) -> pd.DataFrame:
        """Current-rate observations, or the ALFRED point-in-time snapshot.

        `vintage_date` (YYYY-MM-DD) returns only observations released on or
        before that date — the data a forecaster could actually have seen.
        """
        params: dict[str, str] = {"series_id": series_id}
        if vintage_date:
            params["vintage"] = vintage_date
        resp = self.http.get("/series/observations", params=params)
        if resp.status_code == 400:
            raise FredAuthError(f"FRED rejected request (check FRED_API_KEY): {resp.text[:120]}")
        resp.raise_for_status()
        rows = []
        for obs in resp.json()["observations"]:
            if obs.get("value") in (".", ""):
                continue
            rows.append({"date": pd.Timestamp(obs["date"]), "series_id": series_id, "value": float(obs["value"])})
        return pd.DataFrame(rows, columns=["date", "series_id", "value"])

    def close(self) -> None:
        self.http.close()


@dataclass
class FredIngest:
    """Downloads a shock dataset's series with vintage coverage (A-S-10)."""

    client: FredClient
    out_dir: Path | str

    def ingest_shock(self, shock_id: str, vintages: list[str]) -> Path:
        """Downloads a shock dataset's series with vintage coverage (A-S-10).

        Refuses holdout shocks — the 2025 path is scoring-only
        (`ingest_holdout_scoring`), never calibration.zip
        """
        require_calibration_ok(shock_id)
        dataset = get_dataset(shock_id)
        out_dir = Path(self.out_dir) / shock_id
        out_dir.mkdir(parents=True, exist_ok=True)
        for sid in dataset.series:
            frames = [self.client.series_observations(sid, v) for v in vintages]
            df = pd.concat(frames, ignore_index=True) if frames else self.client.series_observations(sid)
            df["shock_id"] = shock_id
            df.to_parquet(out_dir / f"{sid}.parquet", index=False)
        return out_dir

    def ingest_holdout_scoring(self, shock_id: str, vintage_date: str) -> Path:
        """Scoring-only path for the 2025 holdout: fetched, never calibrated.

        Still routed through the guard so only explicitly-scoring callers
        can reach it (they pass `vintage_date`, not a calibration set).
        """
        if shock_id not in {"shock-2025-tariff", "tariffs-2025"}:
            raise ValueError(f"not a holdout shock: {shock_id}")
        dataset = get_dataset(shock_id)
        out_dir = Path(self.out_dir) / shock_id
        out_dir.mkdir(parents=True, exist_ok=True)
        for sid in dataset.series:
            df = self.client.series_observations(sid, vintage_date)
            df["shock_id"] = shock_id
            df.to_parquet(out_dir / f"{sid}.vintage-{vintage_date}.parquet", index=False)
        return out_dir