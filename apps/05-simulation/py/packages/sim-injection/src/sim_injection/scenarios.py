"""A-S-24 shock-scenarios: the 4 scenarios, wired to the G-02 package data
via the verified mirror (scenarios.mirror.json, single-sourced from the
frozen @substrate/scenarios TS). The 2025 tariff wave remains flagged as the
end-to-end HOLDOUT at every consumption point.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .spec import InjectionSpec, validate_shock_spec

MIRROR_PATH = Path(__file__).resolve().parent / "scenarios.mirror.json"
MIRROR_VERSION = "1.0.0"

HOLDOUT_SCENARIO_IDS = frozenset({"tariffs-2025"})


@dataclass(frozen=True)
class ShockScenarioRef:
    id: str
    name: str
    realizedOutcome: str
    window: str
    seed: str
    series: tuple[str, ...]
    version: str = "1.0.0"

    @property
    def is_holdout(self) -> bool:
        return self.id in HOLDOUT_SCENARIO_IDS


def _load() -> list[ShockScenarioRef]:
    raw = json.loads(MIRROR_PATH.read_text())
    assert raw["version"] == MIRROR_VERSION, "scenarios mirror version drift"
    return [
        ShockScenarioRef(
            id=s["id"],
            name=s["name"],
            realizedOutcome=s["realizedOutcome"],
            window=s["window"],
            seed=s["seed"],
            series=tuple(s.get("series", [])),
        )
        for s in raw["scenarios"]
    ]


SCENARIOS: list[ShockScenarioRef] = _load()
_BY_ID = {s.id: s for s in SCENARIOS}


def list_scenarios() -> list[str]:
    return [s.id for s in SCENARIOS]


def get_scenario(scenario_id: str) -> ShockScenarioRef:
    try:
        return _BY_ID[scenario_id]
    except KeyError:
        raise KeyError(f"unknown shock scenario: {scenario_id}") from None


def scenario_for_dataset(dataset_id: str) -> ShockScenarioRef:
    """Map a shock dataset (shock-2024-...) to its C6 scenario id."""
    mapping = {
        "shock-2020-pandemic": "covid-2020",
        "shock-2021-supplychain": "supplychain-2021",
        "shock-2022-inflation": "inflation-2022",
        "shock-2025-tariff": "tariffs-2025",
    }
    return get_scenario(mapping[dataset_id])