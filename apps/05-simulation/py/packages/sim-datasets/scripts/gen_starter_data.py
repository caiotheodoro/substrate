#!/usr/bin/env python3
"""Regenerates the bundled starter datasets (A-S-06..09).

Hand-curated monthly series with REAL historical anchors (marked
quality=anchor) and log-linear interpolation between anchors (marked
quality=interpolated). These are PLACEHOLDER data with real anchors:
fred-ingest (A-S-10) replaces them with ALFRED point-in-time vintages.

Run:  uv run python scripts/gen_starter_data.py
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "src" / "sim_datasets" / "data"

MONTHS = [f"{y:04d}-{m:02d}" for y in range(2019, 2026) for m in range(1, 13)]

# Each series: name, units, source series id, list of (date, value) anchors.
SERIES: dict[str, tuple[str, str, list[tuple[str, float]]]] = {
    "UNRATE": ("Civilian Unemployment Rate", "percent", [
        ("2019-01", 4.0), ("2019-12", 3.5), ("2020-01", 3.6), ("2020-02", 3.5),
        ("2020-03", 4.4), ("2020-04", 14.7), ("2020-05", 13.3), ("2020-06", 11.1),
        ("2020-07", 10.2), ("2020-08", 8.4), ("2020-09", 7.9), ("2020-10", 6.9),
        ("2020-11", 6.7), ("2020-12", 6.7),
    ]),
    "RSAFS_INDEX": ("Retail and Food Services Sales (index, 2019-01=100)", "index", [
        ("2019-01", 100.0), ("2019-12", 102.0), ("2020-01", 102.5), ("2020-02", 102.3),
        ("2020-03", 93.4), ("2020-04", 78.1), ("2020-05", 91.9), ("2020-06", 99.6),
        ("2020-07", 100.5), ("2020-08", 101.7), ("2020-09", 103.5), ("2020-10", 103.9),
        ("2020-11", 102.5), ("2020-12", 101.5), ("2021-01", 108.6), ("2021-02", 104.4),
        ("2021-03", 112.4), ("2021-04", 113.9), ("2021-05", 113.0), ("2021-06", 113.9),
        ("2021-12", 121.0),
    ]),
    "CPIAUCSL_YOY": ("CPI-U All Items, YoY", "percent", [
        ("2019-01", 2.1), ("2019-12", 2.3), ("2020-01", 2.5), ("2020-02", 2.3),
        ("2020-03", 1.5), ("2020-04", 0.3), ("2020-05", 0.1), ("2020-06", 0.6),
        ("2020-07", 1.0), ("2020-08", 1.3), ("2020-09", 1.4), ("2020-10", 1.2),
        ("2020-11", 1.2), ("2020-12", 1.4), ("2021-01", 1.4), ("2021-04", 4.2),
        ("2021-06", 5.4), ("2021-09", 5.4), ("2021-10", 6.2), ("2021-11", 6.8),
        ("2021-12", 7.0), ("2022-01", 7.5), ("2022-02", 7.9), ("2022-03", 8.5),
        ("2022-04", 8.3), ("2022-05", 8.6), ("2022-06", 9.1), ("2022-07", 8.5),
        ("2022-08", 8.3), ("2022-09", 8.2), ("2022-10", 7.7), ("2022-11", 7.1),
        ("2022-12", 6.5),
    ]),
    "INDPRO_INDEX": ("Industrial Production (index, 2019-01=100)", "index", [
        ("2019-01", 100.0), ("2019-12", 101.0), ("2020-01", 101.0), ("2020-02", 101.1),
        ("2020-03", 96.7), ("2020-04", 85.9), ("2020-05", 87.1), ("2020-06", 92.5),
        ("2020-07", 94.2), ("2020-08", 95.5), ("2020-09", 95.8), ("2020-10", 96.4),
        ("2020-11", 96.7), ("2020-12", 96.5),
    ]),
    "PPIACO_YOY": ("PPI All Commodities, YoY", "percent", [
        ("2020-01", 0.5), ("2020-02", 0.6), ("2020-03", -0.7), ("2020-05", -0.8), ("2020-12", 0.8), ("2021-01", 1.3),
        ("2021-02", 2.6), ("2021-03", 4.2), ("2021-04", 6.2), ("2021-05", 6.6),
        ("2021-06", 7.3), ("2021-07", 7.8), ("2021-08", 8.3), ("2021-09", 8.6),
        ("2021-10", 8.6), ("2021-11", 9.7), ("2021-12", 9.7), ("2022-01", 9.7),
        ("2022-03", 11.2), ("2022-06", 11.3), ("2022-09", 8.5), ("2022-12", 6.2),
    ]),
    "ISMMAN_SUPPLIER_DELIVERIES": ("ISM Manufacturing Supplier Deliveries", "index", [
        ("2020-01", 51.2), ("2020-03", 65.9), ("2020-04", 76.1), ("2020-05", 67.7),
        ("2020-08", 63.9), ("2020-12", 60.8), ("2021-01", 61.9), ("2021-02", 66.2),
        ("2021-03", 74.4), ("2021-04", 75.1), ("2021-05", 78.8), ("2021-06", 75.3),
        ("2021-07", 72.5), ("2021-08", 69.4), ("2021-09", 73.4), ("2021-10", 72.2),
        ("2021-11", 72.2), ("2021-12", 64.9),
    ]),
    "FREIGHT_INDEX": ("Container Freight Spot Rate (index, 2020-01=100)", "index", [
        ("2020-01", 100.0), ("2020-06", 88.0), ("2020-12", 140.0), ("2021-01", 150.0),
        ("2021-03", 155.0), ("2021-05", 185.0), ("2021-07", 220.0), ("2021-09", 245.0),
        ("2021-10", 250.0), ("2021-12", 205.0),
    ]),
    "PCEPILFE_YOY": ("Core PCE Price Index, YoY", "percent", [
        ("2021-01", 1.4), ("2021-04", 3.1), ("2021-12", 4.9), ("2022-01", 5.1),
        ("2022-02", 5.4), ("2022-03", 5.3), ("2022-04", 4.9), ("2022-05", 4.7),
        ("2022-06", 4.8), ("2022-09", 5.1), ("2022-12", 4.9),
    ]),
    "FEDFUNDS": ("Effective Federal Funds Rate", "percent", [
        ("2021-01", 0.09), ("2021-12", 0.08), ("2022-03", 0.33), ("2022-04", 0.33),
        ("2022-05", 0.77), ("2022-06", 1.58), ("2022-07", 1.68), ("2022-08", 2.33),
        ("2022-09", 2.56), ("2022-10", 3.08), ("2022-11", 3.83), ("2022-12", 4.33),
    ]),
    "IMPGSA": ("US Imports of Goods (NSA, $B/month)", "billion-usd", [
        ("2024-01", 332.0), ("2024-12", 352.0), ("2025-01", 344.0), ("2025-02", 347.0),
        ("2025-03", 368.0), ("2025-04", 312.0), ("2025-05", 295.0), ("2025-06", 288.0),
        ("2025-07", 294.0), ("2025-08", 310.0), ("2025-09", 325.0), ("2025-10", 318.0),
        ("2025-11", 330.0), ("2025-12", 340.0),
    ]),
    "CUSVMV": ("US Customs Duties Collected ($B/month)", "billion-usd", [
        ("2024-01", 7.8), ("2024-12", 8.2), ("2025-01", 9.2), ("2025-02", 9.8),
        ("2025-03", 13.5), ("2025-04", 12.4), ("2025-05", 13.8), ("2025-06", 15.1),
        ("2025-07", 14.2), ("2025-08", 14.8), ("2025-09", 15.6), ("2025-10", 14.0),
        ("2025-11", 15.2), ("2025-12", 16.1),
    ]),
    "DCOILWTICO": ("WTI Crude Oil Spot Price", "usd-per-bbl", [
        ("2024-01", 73.0), ("2024-12", 69.0), ("2025-01", 74.0), ("2025-02", 71.0),
        ("2025-03", 68.0), ("2025-04", 61.0), ("2025-05", 59.0), ("2025-06", 65.0),
        ("2025-07", 67.0), ("2025-08", 66.0), ("2025-09", 65.0), ("2025-10", 71.0),
        ("2025-11", 68.0), ("2025-12", 66.0),
    ]),
    "FRGSREC": ("Atlanta Fed GDPNow-implied real GDP growth (annualized)", "percent", [
        ("2024-01", 2.3), ("2024-12", 2.4), ("2025-01", 2.5), ("2025-02", 2.6),
        ("2025-03", 1.8), ("2025-04", -2.2), ("2025-05", 0.8), ("2025-06", 1.5),
        ("2025-07", 1.2), ("2025-08", 1.0), ("2025-09", 2.2), ("2025-10", 2.4),
        ("2025-11", 2.6), ("2025-12", 2.3),
    ]),
}

SHOCKS: dict[str, dict] = {
    "shock-2020-pandemic": {
        "id": "shock-2020-pandemic",
        "scenario_id": "covid-2020",
        "name": "2020 Pandemic Demand Shift",
        "window": "2020-03/2020-06",
        "holdout": False,
        "series": ["UNRATE", "RSAFS_INDEX", "CPIAUCSL_YOY", "INDPRO_INDEX"],
        "support": ["2019-01", "2020-12"],
    },
    "shock-2021-supplychain": {
        "id": "shock-2021-supplychain",
        "scenario_id": "supplychain-2021",
        "name": "2021 Supply Chain Crisis",
        "window": "2021",
        "holdout": False,
        "series": ["PPIACO_YOY", "ISMMAN_SUPPLIER_DELIVERIES", "FREIGHT_INDEX", "RSAFS_INDEX"],
        "support": ["2020-01", "2021-12"],
    },
    "shock-2022-inflation": {
        "id": "shock-2022-inflation",
        "scenario_id": "inflation-2022",
        "name": "2022 Inflation Spike",
        "window": "2022",
        "holdout": False,
        "series": ["CPIAUCSL_YOY", "PCEPILFE_YOY", "FEDFUNDS", "PPIACO_YOY"],
        "support": ["2021-01", "2022-12"],
    },
    "shock-2025-tariff": {
        "id": "shock-2025-tariff",
        "scenario_id": "tariffs-2025",
        "name": "2025 Tariff Waves (HOLDOUT)",
        "window": "2025",
        "holdout": True,
        "series": ["FRGSREC", "CUSVMV", "IMPGSA", "DCOILWTICO"],
        "support": ["2024-01", "2025-12"],
    },
}


def interpolate(anchors: list[tuple[str, float]]) -> list[tuple[str, float, str]]:
    linear = any(v <= 0 for _, v in anchors)
    rows: list[tuple[str, float, str]] = []
    first, last = anchors[0][0], anchors[-1][0]
    anchor_pos = {d: v for d, v in anchors}
    for i, month in enumerate(MONTHS):
        if month < first or month > last:
            continue
        if month in anchor_pos:
            rows.append((month, anchor_pos[month], "anchor"))
            continue
        # find bracketing anchors
        j = 0
        while j < len(anchors) - 2 and not (anchors[j][0] < month < anchors[j + 1][0]):
            j += 1
        prev_date, prev_val = anchors[j]
        next_date, next_val = anchors[j + 1]
        span = MONTHS.index(next_date) - MONTHS.index(prev_date)
        frac = (i - MONTHS.index(prev_date)) / span
        if linear:
            value = prev_val + frac * (next_val - prev_val)
        else:
            logv = math.log(prev_val) + frac * (math.log(next_val) - math.log(prev_val))
            value = math.exp(logv)
        rows.append((month, value, "interpolated"))
    return rows


def main() -> None:
    for shock_id, meta in SHOCKS.items():
        out_dir = DATA / shock_id
        out_dir.mkdir(parents=True, exist_ok=True)
        for series_id in meta["series"]:
            name, units, anchors = SERIES[series_id]
            rows = interpolate(anchors)
            path = out_dir / f"{series_id}.csv"
            with path.open("w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["date", "series_id", "value", "quality"])
                for date, value, quality in rows:
                    writer.writerow([date, series_id, f"{value:.4f}", quality])
        meta_path = out_dir / "metadata.json"
        meta_path.write_text(json.dumps(meta, indent=2) + "\n")
        print(f"wrote {shock_id} ({len(meta['series'])} series)")


if __name__ == "__main__":
    main()