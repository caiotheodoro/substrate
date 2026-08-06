"""M2 — Historical Shock Datasets (A-S-06..A-S-11).

Bundles hand-curated STARTER data (real annual/monthly anchors,
logged in `data/*/metadata.json`) that fred-ingest (A-S-10) replaces with
ALFRED point-in-time vintages. The `shock-2025-tariff` dataset is the
end-to-end HOLDOUT: every calibration entry point refuses it.
"""

from .datasets import (
    HOLDOUT_IDS,
    HoldoutError,
    ShockDataset,
    available_shocks,
    get_dataset,
    require_calibration_ok,
)
from .catalog import MacroCatalog, MacroSeries, load_catalog
from .fred import FredClient, FredIngest

__all__ = [
    "HoldoutError",
    "ShockDataset",
    "available_shocks",
    "get_dataset",
    "require_calibration_ok",
    "MacroCatalog",
    "MacroSeries",
    "load_catalog",
    "FredClient",
    "FredIngest",
]