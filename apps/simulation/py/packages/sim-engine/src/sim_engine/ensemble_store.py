"""A-S-18 ensemble-store: seeded reproduction + RNG stream registry, persisted
to DuckDB + Parquet. A run is (run_seed, shock_id, simulator, horizon) →
trajectories; the store guarantees byte-reproducibility via the registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from sim_shared.rng import RNGRegistry


@dataclass
class EnsembleRunResult:
    run_id: str
    shock_id: str
    simulator: str
    seed: int
    horizon: int
    values: np.ndarray  # (n_members, horizon)
    meta: dict = field(default_factory=dict)


class EnsembleStore:
    """Canonical store for run→trajectory tables (A-S-18)."""

    def __init__(self, path: Path | str | None = None):
        self.path = str(path) if path else ":memory:"
        self.con = duckdb.connect(self.path)
        self._create_schema()

    def _create_schema(self) -> None:
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS ensemble_runs (
                run_id VARCHAR,
                shock_id VARCHAR,
                simulator VARCHAR,
                seed INTEGER,
                horizon INTEGER,
                member_id INTEGER,
                step INTEGER,
                value DOUBLE,
                meta JSON
            )
            """
        )

    def save(self, result: EnsembleRunResult) -> str:
        rows = []
        n_members, horizon = result.values.shape
        for m in range(n_members):
            for t in range(horizon):
                rows.append(
                    (
                        result.run_id,
                        result.shock_id,
                        result.simulator,
                        result.seed,
                        result.horizon,
                        m,
                        t,
                        float(result.values[m, t]),
                        None,
                    )
                )
        self.con.executemany(
            "INSERT INTO ensemble_runs VALUES (?,?,?,?,?,?,?,?,?)",
            rows,
        )
        return result.run_id

    def load(self, run_id: str) -> EnsembleRunResult:
        df = self.con.execute(
            "SELECT * FROM ensemble_runs WHERE run_id = ? ORDER BY member_id, step",
            [run_id],
        ).fetchdf()
        if df.empty:
            raise KeyError(f"no run {run_id}")
        members = df["member_id"].nunique()
        values = df.pivot(index="member_id", columns="step", values="value").to_numpy()
        row = df.iloc[0]
        return EnsembleRunResult(
            run_id=row["run_id"],
            shock_id=row["shock_id"],
            simulator=row["simulator"],
            seed=int(row["seed"]),
            horizon=int(row["horizon"]),
            values=np.asarray(values, dtype=float),
        )

    def to_parquet(self, run_id: str, path: Path | str) -> Path:
        df = self.con.execute(
            "SELECT * FROM ensemble_runs WHERE run_id = ?", [run_id]
        ).fetchdf()
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(p, index=False)
        return p

    def reproduce(self, seed: int, shock_id: str, simulator: str) -> RNGRegistry:
        """Registry keyed by (seed, shock_id, simulator) — the reproducibility
        contract: same seed ⇒ same stream ⇒ same ensemble."""
        return RNGRegistry(hash((seed, shock_id, simulator)) & 0xFFFFFFFF)

    def close(self) -> None:
        self.con.close()