"""A-S-04 — simbench-report: coverage tables, reliability, win/lose partition.

v1 ships the tables as JSON; the Quarto+Plotly workbook is deferred to v2.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

COVERAGE_COLS = ["coverage_50", "coverage_80", "coverage_95"]
NOMINAL = {"coverage_50": 0.50, "coverage_80": 0.80, "coverage_95": 0.95}


def build_report(frame, baseline: str | None = None) -> dict:
    """frame: simbench matrix DataFrame. Partitions into win/lose on CRPS and
    tail-loss vs `baseline` when provided."""
    from pandas import DataFrame

    frame = frame.copy() if isinstance(frame, DataFrame) else DataFrame(frame)
    out: dict = {}

    # coverage tables per (shock, method)
    out["coverage"] = (
        frame.groupby(["shock_id", "method"])[COVERAGE_COLS].mean().round(4).to_dict(orient="index")
    )

    # reliability: empirical coverage vs nominal across all runs
    abs_errors = []
    for col, nominal in NOMINAL.items():
        empirical = float(frame[col].mean())
        err = abs(empirical - nominal)
        out[col] = round(empirical, 4)
        out[f"abs_error_{col}"] = round(err, 4)
        abs_errors.append(err)
    out["reliability_mean_abs_error"] = round(float(np.mean(abs_errors)), 4)

    # win/lose partition vs baseline on CRPS (primary metric)
    if baseline is not None and frame["method"].nunique() > 1:
        base = frame[frame["method"] == baseline]
        challengers = frame[frame["method"] != baseline]
        merged = challengers.merge(
            base[["shock_id", "seed", "crps"]],
            on=["shock_id", "seed"],
            suffixes=("", "_base"),
        )
        delta = merged["crps"] - merged["crps_base"]
        out["win_lose"] = {
            "vs": baseline,
            "metric": "crps",
            "wins": int((delta < 0).sum()),
            "losses": int((delta > 0).sum()),
            "ties": int((delta == 0).sum()),
        }
    return out


def write_report(report: dict, out: str | Path) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    return out