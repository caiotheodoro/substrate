"""A-S-03 — simbench-registry: SimulatorAdapter plugin registry on SQLite.

Persists adapter registrations and mirrors them into the in-memory adapter
SDK so SimBench can replay a matrix against the same plugins that ran it.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class AdapterRegistry:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS adapters (
                method TEXT PRIMARY KEY,
                module TEXT NOT NULL,
                registered_at TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def register(self, method: str, module: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO adapters (method, module, registered_at) VALUES (?, ?, ?)",
            (method, module, datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()

    def list(self) -> list[str]:
        return [r[0] for r in self._conn.execute("SELECT method FROM adapters ORDER BY method")]

    def close(self) -> None:
        self._conn.close()