"""Storage backends: in-memory KV (tests/CI default) and Postgres.

All pg-backed atoms (telemetry A-K-09, canonicalization A-K-15, verdict
A-K-27, freshness ledger A-K-24, human queue A-K-14) are implemented against
a single tiny KV interface so the in-memory variant is the default in tests
and the Postgres variant is one constructor away.
"""

from __future__ import annotations

import json
import time
from typing import Any, Iterator

import numpy as np

try:  # pragma: no cover - import guard for optional pg backend
    import psycopg  # type: ignore
    from psycopg.rows import dict_row

    _PSYCOPG_AVAILABLE = True
except ImportError:  # pragma: no cover
    psycopg = None  # type: ignore
    _PSYCOPG_AVAILABLE = False


class Store:
    """KV interface with namespaced keys. Values are JSON-serializable dicts."""

    def put(self, key: str, value: dict[str, Any]) -> None: ...
    def get(self, key: str) -> dict[str, Any] | None: ...
    def delete(self, key: str) -> None: ...
    def scan(self, prefix: str) -> Iterator[tuple[str, dict[str, Any]]]: ...
    def count(self, prefix: str | None = None) -> int: ...


class InMemoryStore(Store):
    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    def put(self, key: str, value: dict[str, Any]) -> None:
        self._data[key] = value

    def get(self, key: str) -> dict[str, Any] | None:
        return self._data.get(key)

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def scan(self, prefix: str) -> Iterator[tuple[str, dict[str, Any]]]:
        for key in sorted(self._data):
            if key.startswith(prefix):
                yield key, self._data[key]

    def count(self, prefix: str | None = None) -> int:
        if prefix is None:
            return len(self._data)
        return sum(1 for k in self._data if k.startswith(prefix))


class PostgresStore(Store):
    """Generic key-value table over the shared Postgres 17 instance.

    One table `substrate_knowledge_kv(kind, key, value jsonb, updated_at)`.
    Create the table with `ensure_schema()`. psycopg is an optional import;
    constructing this store without psycopg installed raises.
    """

    def __init__(self, dsn: str) -> None:
        if not _PSYCOPG_AVAILABLE:
            raise RuntimeError("psycopg not installed; PostgresStore unavailable")
        self.dsn = dsn
        self._conn: Any = None

    def _connection(self) -> Any:
        if self._conn is None:
            self._conn = psycopg.connect(self.dsn, row_factory=dict_row)
            self.ensure_schema()
        return self._conn

    def ensure_schema(self) -> None:
        conn = self._conn
        if conn is None:
            conn = psycopg.connect(self.dsn, row_factory=dict_row)
            self._conn = conn
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS substrate_knowledge_kv (
                    kind text NOT NULL,
                    key text NOT NULL,
                    value jsonb NOT NULL,
                    updated_at timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (kind, key)
                )
                """
            )
        conn.commit()

    @staticmethod
    def _split(key: str) -> tuple[str, str]:
        kind, _, rest = key.partition(":")
        return kind, rest

    def put(self, key: str, value: dict[str, Any]) -> None:
        kind, rest = self._split(key)
        conn = self._connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO substrate_knowledge_kv (kind, key, value, updated_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT (kind, key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
                """,
                (kind, rest, json.dumps(value, default=str)),
            )
        conn.commit()

    def get(self, key: str) -> dict[str, Any] | None:
        kind, rest = self._split(key)
        conn = self._connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT value FROM substrate_knowledge_kv WHERE kind = %s AND key = %s",
                (kind, rest),
            )
            row = cur.fetchone()
        return dict(row["value"]) if row else None

    def delete(self, key: str) -> None:
        kind, rest = self._split(key)
        conn = self._connection()
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM substrate_knowledge_kv WHERE kind = %s AND key = %s",
                (kind, rest),
            )
        conn.commit()

    def scan(self, prefix: str) -> Iterator[tuple[str, dict[str, Any]]]:
        kind, rest = self._split(prefix)
        conn = self._connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT key, value FROM substrate_knowledge_kv
                WHERE kind = %s AND key >= %s ORDER BY key
                """,
                (kind, rest),
            )
            rows = cur.fetchall()
        for row in rows:
            yield f"{kind}:{row['key']}", dict(row["value"])

    def count(self, prefix: str | None = None) -> int:
        conn = self._connection()
        with conn.cursor() as cur:
            if prefix is None:
                cur.execute("SELECT count(*) AS n FROM substrate_knowledge_kv")
            else:
                kind, rest = self._split(prefix)
                cur.execute(
                    "SELECT count(*) AS n FROM substrate_knowledge_kv WHERE kind = %s AND key >= %s",
                    (kind, rest),
                )
            return int(cur.fetchone()["n"])  # type: ignore[index]


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    return float(np.quantile(np.asarray(values, dtype=float), q))
