"""A-S-19 simulator-adapter-sdk: score ANY simulator through a plugin contract.

A SimulatorAdapter takes a world seed (dict) + horizon + RNG and returns an
EnsembleForecast. SimBench's registry (M1) consumes this contract; plugins
can self-register via the `substrate.simulator_adapters` entry point group
or explicit registration.
"""

from __future__ import annotations

import importlib.metadata as importlib_metadata
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np


@dataclass
class EnsembleForecast:
    """The scored object: one distribution per horizon step."""

    values: np.ndarray  # (n_members, horizon)
    horizon: int
    member_ids: list[str] = field(default_factory=list)
    as_of: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.values = np.asarray(self.values, dtype=float)
        if self.horizon <= 0:
            self.horizon = self.values.shape[1]

    def quantile(self, q: float) -> np.ndarray:
        return np.quantile(self.values, q, axis=0)

    def interval(self, level: float) -> tuple[np.ndarray, np.ndarray]:
        lo = (1 - level) / 2
        return self.quantile(lo), self.quantile(1 - lo)

    def point(self) -> np.ndarray:
        return self.quantile(0.5)


class SimulatorAdapter(Protocol):
    """Any object with `simulate(...)` can be scored by SimBench."""

    method: str

    def simulate(
        self,
        world_seed: dict[str, Any],
        horizon: int,
        rng: np.random.Generator,
        n_members: int,
    ) -> EnsembleForecast: ...


_ADAPTERS: dict[str, Any] = {}


def register_adapter(adapter: Any) -> Any:
    _ADAPTERS[adapter.method] = adapter
    return adapter


def remove_adapter(method: str) -> None:
    _ADAPTERS.pop(method, None)


def get_adapter(method: str) -> Any:
    try:
        return _ADAPTERS[method]
    except KeyError:
        raise KeyError(f"no registered simulator adapter: {method}") from None


def list_adapters() -> list[str]:
    return sorted(_ADAPTERS)


def discover_entrypoints(group: str = "substrate.simulator_adapters") -> list[str]:
    found = []
    for ep in importlib_metadata.entry_points(group=group):
        try:
            adapter = ep.load()
            register_adapter(adapter)
            found.append(ep.name)
        except Exception:
            continue
    return found