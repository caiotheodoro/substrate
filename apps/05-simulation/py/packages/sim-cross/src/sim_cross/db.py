"""A-S-14 — sim-db: DuckDB persistence for simulation runs.

Tables:
  - runs:  (run_id, shock_id, method, seed, as_of, run_at)
  - events: (run_id, seq, kind, agent, payload_json)  — C1 social log
  - scores: (shock_id, method, seed, as_of, score_json) — SimBench matrix rows

Writes are append-only (INSERT) and queryable via DuckDB SQL.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb
import pandas as pd


class SimDB:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self.con = duckdb.connect(self.path)
        self.con.execute("CREATE TABLE IF NOT EXISTS runs (run_id VARCHAR, shock_id VARCHAR, method VARCHAR, seed BIGINT, as_of VARCHAR, run_at TIMESTAMP)")
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS events (run_id VARCHAR, seq BIGINT, kind VARCHAR, agent VARCHAR, payload_json VARCHAR)"
        )
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS scores (shock_id VARCHAR, method VARCHAR, seed BIGINT, as_of VARCHAR, score_json VARCHAR)"
        )

    def add_run(self, run_id: str, shock_id: str, method: str, seed: int, as_of: str) -> None:
        self.con.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)",
            [run_id, shock_id, method, seed, as_of, datetime.now(timezone.utc)],
        )

    def add_event(self, run_id: str, seq: int, kind: str, agent: str, payload: dict[str, Any]) -> None:
        self.con.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?, ?)",
            [run_id, seq, kind, agent, json.dumps(payload)],
        )

    def add_scores(self, frame: pd.DataFrame) -> int:
        n = 0
        for _, row in frame.iterrows():
            self.con.execute(
                "INSERT INTO scores VALUES (?, ?, ?, ?, ?)",
                [str(row["shock_id"]), str(row["method"]), int(row["seed"]), str(row["as_of"]),
                 json.dumps(row.drop(labels=["shock_id", "method", "seed", "as_of"]).to_dict())],
            )
            n += 1
        return n

    def runs_df(self) -> pd.DataFrame:
        return self.con.execute("SELECT * FROM runs").df()

    def events_df(self, run_id: str) -> pd.DataFrame:
        return self.con.execute("SELECT * FROM events WHERE run_id = ?", [run_id]).df()

    def scores_df(self) -> pd.DataFrame:
        return self.con.execute("SELECT * FROM scores").df()

    def close(self) -> None:
        self.con.close()