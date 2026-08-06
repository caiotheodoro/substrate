"""A-S-02 — simbench-runner: 4 shocks × seeds × simulators → Parquet scores.

Refuses non-vintaged runs (BUILD.md integrity rule #1): every scored run
must carry an `as_of` vintage through the world seed, and the datasets
package raises HoldoutError for the 2025 tariff wave outside scoring mode.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from sim_bench.scoring import score_ensemble
from sim_datasets import require_calibration_ok

DEFAULT_SHOCK_IDS = ["shock-2020-pandemic", "shock-2021-supplychain", "shock-2022-inflation"]


class BenchMatrixRunner:
    def __init__(self, adapters: dict, datasets: dict, rng_seed: int = 0):
        """adapters: method -> SimulatorAdapter; datasets: shock_id -> ShockDataset."""
        self.adapters = adapters
        self.datasets = datasets
        self._rng = np.random.default_rng(rng_seed)

    def run(
        self,
        shock_ids: list[str] | None = None,
        seeds: list[int] | None = None,
        n_members: int = 100,
    ) -> pd.DataFrame:
        shock_ids = shock_ids or DEFAULT_SHOCK_IDS
        seeds = seeds or [0, 1, 2]
        rows = []
        for shock_id in shock_ids:
            require_calibration_ok(shock_id)  # integrity rule 2: 2025 HOLDOUT refused
            dataset = self.datasets[shock_id]
            realized_df = dataset.realized_path()
            realized = realized_df["value"].to_numpy(dtype=float)
            # lookahead-free world seed: PRE-SHOCK history only; the vintage
            # (`as_of`) defaults to the shock window start (the decision date)
            from sim_injection import build_shock_seed

            world_seed = build_shock_seed(dataset.scenario_id, config={"seed": 0})
            as_of = str(world_seed["as_of"])
            for method, adapter in self.adapters.items():
                for seed in seeds:
                    rng = np.random.default_rng(seed)
                    forecast = adapter.simulate(
                        world_seed=world_seed,
                        horizon=realized.size,
                        rng=rng,
                        n_members=n_members,
                    )
                    result = score_ensemble(
                        forecast,
                        realized,
                        meta={
                            "shock_id": shock_id,
                            "as_of": str(as_of),
                            "method": method,
                            "seed": seed,
                            "vintaged": True,
                        },
                    )
                    row = {
                        "shock_id": shock_id,
                        "as_of": str(as_of),
                        "method": method,
                        "seed": seed,
                        "vintaged": True,
                    }
                    row.update(result.scores)
                    rows.append(row)
        return pd.DataFrame(rows)

    def save(self, frame: pd.DataFrame, out: str | Path) -> Path:
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(out, index=False)
        return out