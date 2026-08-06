"""Reference behavioral simulator adapter (powered by swarm-core) — the
plugin that SimBench's matrix exercises. It is deliberately generic and
calibration-agnostic: all parameters come from the world seed (pre-shock
beliefs), never from the realized outcome, so retro-validation measures the
simulator against history without tuning to it (BUILD integrity rule 2).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from sim_shared.rng import RNGRegistry

from .adapter_sdk import EnsembleForecast, register_adapter
from .world import Sector, World  # noqa: F401  (world construction SDK surface)


class CascadeBehaviourAdapter:
    """Whole-population behavioral sim: agents weigh beliefs on each unit of
    history; aggregate activity drives the next level. Deterministic in seed."""

    method = "cascade-behaviour"

    def simulate(
        self,
        world_seed: dict[str, Any],
        horizon: int,
        rng: np.random.Generator,
        n_members: int,
    ) -> EnsembleForecast:
        history = [float(v) for v in world_seed.get("history", [])]
        if not history:
            raise ValueError("world_seed['history'] required")
        cfg = dict(world_seed.get("world", {}))
        cascade = float(cfg.get("cascade", 0.0))  # pre-shock perceived shift risk
        shift = float(cfg.get("shift_magnitude", 0.1))
        agents = int(cfg.get("agents", 40))
        drift = float(cfg.get("drift", 0.001))
        vol = float(cfg.get("vol", 0.03))
        noise = float(cfg.get("noise", 0.01))
        seed = int(world_seed.get("seed", 0))

        reg = RNGRegistry(seed)
        members = np.zeros((n_members, horizon))
        log_hist = np.log(np.asarray(history, dtype=float))
        base = log_hist[-1]
        recent = float(np.mean(np.diff(log_hist[-8:]))) if len(log_hist) > 1 else drift
        for m in range(n_members):
            mrng = reg.generator(f"member:{m}")
            regime = bool(mrng.random() < cascade)  # this member "notices" the shift
            path = np.zeros(horizon)
            path[0] = base
            for t in range(1, horizon):
                upvotes = 0
                for _ in range(agents):
                    belief = recent + drift + float(mrng.normal(0, vol))
                    if regime:
                        belief += shift
                    upvotes += int(belief > 0)
                activity = (upvotes / agents) * 2.0 - 1.0
                # activity is monthly log-growth: ~±5%/mo for macro variables
                growth = drift + 0.05 * activity + float(mrng.normal(0, noise))
                path[t] = path[t - 1] + growth
            members[m] = np.exp(path)
        return EnsembleForecast(
            values=members,
            horizon=horizon,
            member_ids=[f"cascade-m{m}" for m in range(n_members)],
            meta={"method": self.method, "seed": seed},
        )


register_adapter(CascadeBehaviourAdapter())