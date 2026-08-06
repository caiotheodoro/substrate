"""A-S-25 injection-runtime: replayable interventions for sims AND baselines.

An InjectionRuntime turns a C6 shock scenario into an intervention schedule
applied to a sim_engine World, and into the `world_seed` an engine adapter
consumes. Reused by 01's stress-testing through sim-api :8300
(`/injections/{id}/replay` and `/scenarios`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

import numpy as np
import pandas as pd

from sim_datasets import HoldoutError, get_dataset, require_calibration_ok

from .scenarios import get_scenario
from .spec import InjectionSpec

_DATASET_BY_SCENARIO = {
    "covid-2020": "shock-2020-pandemic",
    "supplychain-2021": "shock-2021-supplychain",
    "inflation-2022": "shock-2022-inflation",
    "tariffs-2025": "shock-2025-tariff",
}


@dataclass
class InjectionFrame:
    t: int
    world_snapshot: dict[str, Any]
    multiplier: float


class InjectionRuntime:
    """Apply a shock to a world over a replayable schedule."""

    def __init__(self, world: Any, spec: InjectionSpec):
        self.world = world
        self.spec = spec

    def multiplier_at(self, t: int) -> float:
        m = self.spec.magnitude
        if self.spec.ramp == "linear":
            return m * min(1.0, t / max(1, self.spec.horizon))
        if self.spec.ramp == "exponential" and m > 0:
            return m * (min(1.0, np.exp(t / max(1, self.spec.horizon)) - 1.0))
        return m  # step (and others) hit their nameplate immediately

    def apply(self, t: int) -> float:
        mult = self.multiplier_at(t)
        for channel in self.spec.channels:
            for name in ["goods", "labor", "transport", "finance"]:
                sector = self.world.sectors.get(name)
                if sector is not None:
                    direction = "supply" if channel in ("port-congestion", "inventory", "logistics") else "demand"
                    if channel in ("policy-rate", "tariff-rate", "import-cost"):
                        direction = "price"
                    sector.apply_shock(mult, direction)
        self.world.events.publish(
            "injection",
            {"spec": self.spec.id, "t": t, "multiplier": round(float(mult), 4)},
        )
        return float(mult)

    def replay(self, steps: int) -> Iterator[InjectionFrame]:
        for t in range(steps):
            mult = self.apply(t)
            yield InjectionFrame(t=t, world_snapshot=self.world.snapshot(), multiplier=mult)


def build_shock_seed(
    scenario_id: str,
    as_of: str | None = None,
    series_id: str | None = None,
    config: dict[str, Any] | None = None,
    allow_scoring: bool = False,
) -> dict[str, Any]:
    """world_seed for engine adapters from PRE-SHOCK history only.

    Lookahead rules: `as_of` truncates the realized path (point-in-time), and
    `require_calibration_ok` refuses the 2025 holdout unless the caller
    explicitly declares the scoring path. Never any future data.
    """
    scenario = get_scenario(scenario_id)
    dataset = get_dataset(_DATASET_BY_SCENARIO[scenario_id])
    if dataset.holdout and not allow_scoring:
        require_calibration_ok(dataset.id)
    cfg = dict(config or {})
    sid = cfg.get("series") or dataset.series[0]
    if as_of is None:
        as_of = scenario.window.split("/")[0] + "-01"
    hist_df = dataset.load(series=[sid], as_of=as_of)
    history = hist_df.sort_values("date")["value"].astype(float).tolist()
    if len(history) < 12:
        raise ValueError(f"too little pre-shock history for {scenario_id} as of {as_of}")
    return {
        "scenario_id": scenario_id,
        "as_of": as_of,
        "history": history,
        "world": {
            "cascade": float(cfg.get("cascade", 0.0)),
            "shift_magnitude": float(cfg.get("shift_magnitude", 0.05)),
            "drift": float(cfg.get("drift", 0.0)),
            "vol": float(cfg.get("vol", 0.02)),
            "noise": float(cfg.get("noise", 0.01)),
        },
        "seed": int(cfg.get("seed", 0)),
    }