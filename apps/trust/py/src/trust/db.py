"""A-T-02 trust-db and A-T-03 trust-object-store (v1-lite).

Postgres 16 (``trust`` schema) and MinIO live behind thin protocols so tests
run fully in-memory and offline. The SQL migrations live in
``apps/trust/migrations/`` and are applied by ``make migrate`` /
``run_migrations``; nothing here requires a live database.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Protocol

from trust.contracts import DecisionRecord


class ObjectStore(Protocol):
    """A-T-03 — buckets: artifacts, datasets, models, quarantine."""

    def put(self, key: str, payload: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def list(self, prefix: str = "") -> list[str]: ...


class InMemoryObjectStore:
    """Deterministic in-memory object store (tests, offline runs)."""

    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}

    def put(self, key: str, payload: bytes) -> None:
        self._blobs[key] = payload

    def get(self, key: str) -> bytes:
        if key not in self._blobs:
            raise KeyError(f"no object at {key}")
        return self._blobs[key]

    def list(self, prefix: str = "") -> list[str]:
        return sorted(k for k in self._blobs if k.startswith(prefix))


class MinioObjectStore:
    """A-T-03 against the compose MinIO (:9000). Lazy import — only required
    when the store is actually used."""

    def __init__(self, endpoint: str = "localhost:9000", access_key: str = "substrate", secret_key: str = "substrate-secret", bucket: str = "artifacts", secure: bool = False) -> None:
        self._endpoint = endpoint
        self._bucket = bucket
        self._access = access_key
        self._secret = secret_key
        self._secure = secure
        self._client = None

    def _c(self) -> Any:
        if self._client is None:
            try:
                from minio import Minio  # type: ignore
            except ImportError as e:  # pragma: no cover
                raise RuntimeError("minio client not installed") from e
            self._client = Minio(self._endpoint, access_key=self._access, secret_key=self._secret, secure=self._secure)
        return self._client

    def put(self, key: str, payload: bytes) -> None:
        from io import BytesIO

        client = self._c()
        if not client.bucket_exists(self._bucket):  # pragma: no cover
            client.make_bucket(self._bucket)
        client.put_object(self._bucket, key, BytesIO(payload), len(payload))

    def get(self, key: str) -> bytes:
        from io import BytesIO

        resp = self._c().get_object(self._bucket, key)
        data = resp.read()
        resp.close()
        resp.release_conn()
        return data

    def list(self, prefix: str = "") -> list[str]:
        client = self._c()
        return [o.object_name for o in client.list_objects(self._bucket, prefix=prefix)]


class DecisionLogStore(Protocol):
    """Persistence for C2 rows consumed by M5."""

    def add(self, record: DecisionRecord) -> None: ...
    def fetch_since(self, cursor: str | None, limit: int = 1000) -> tuple[list[DecisionRecord], str]: ...


class InMemoryDecisionLogStore:
    """C2 rows in memory (01's log would be Postgres; tests stay offline)."""

    def __init__(self) -> None:
        self._rows: list[DecisionRecord] = []

    def add(self, record: DecisionRecord) -> None:
        self._rows.append(record)

    def fetch_since(self, cursor: str | None, limit: int = 1000) -> tuple[list[DecisionRecord], str]:
        start = 0
        if cursor is not None:
            for i, r in enumerate(self._rows):
                if r.decisionId == cursor:
                    start = i + 1
                    break
        batch = self._rows[start : start + limit]
        next_cursor = batch[-1].decisionId if batch else (cursor or "")
        return batch, next_cursor


def content_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def run_migrations(dsn: str, migrations_dir: Path | None = None) -> list[str]:
    """Apply migrations/*.sql in order. Lazy psycopg import (ecosystem extra)."""
    base = migrations_dir or Path(__file__).resolve().parents[3] / "migrations"
    applied: list[str] = []
    try:
        import psycopg  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("psycopg not installed; run `uv sync --all-groups`") from e
    with psycopg.connect(dsn, autocommit=True) as conn:
        for sql_path in sorted(base.glob("*.sql")):
            conn.execute(sql_path.read_text())
            applied.append(sql_path.name)
    return applied
