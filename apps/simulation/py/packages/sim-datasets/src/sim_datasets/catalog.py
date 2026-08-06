"""A-S-11 macro-catalog: series registry (units, freq, source, revision policy).

A JSON registry shipped with the package; `load_catalog()` validates and
indexes it. The catalog is the single place a series' point-in-time
discipline is declared — retro paths consume vintages, current paths do not.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parent / "catalog.json"


@dataclass(frozen=True)
class MacroSeries:
    id: str
    name: str
    units: str
    frequency: str
    source: str
    revision_policy: str
    shocks: tuple[str, ...] = ()
    is_holdout: bool = False


@dataclass
class MacroCatalog:
    series: dict[str, MacroSeries] = field(default_factory=dict)

    def get(self, series_id: str) -> MacroSeries:
        try:
            return self.series[series_id]
        except KeyError:
            raise KeyError(f"unknown series: {series_id}") from None

    def for_shock(self, shock_id: str) -> list[MacroSeries]:
        return [s for s in self.series.values() if shock_id in s.shocks]


def load_catalog(path: Path | str = CATALOG_PATH) -> MacroCatalog:
    raw = json.loads(Path(path).read_text())
    catalog = MacroCatalog()
    for entry in raw["series"]:
        s = MacroSeries(
            id=entry["id"],
            name=entry["name"],
            units=entry["units"],
            frequency=entry["frequency"],
            source=entry["source"],
            revision_policy=entry["revision_policy"],
            shocks=tuple(entry.get("shocks", [])),
            is_holdout=bool(entry.get("is_holdout", False)),
        )
        catalog.series[s.id] = s
    return catalog
