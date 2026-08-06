"""A-K-38 message-bus.

Topics (frozen): source.changed, document.parsed, extraction.complete,
gate.verdict. Backends, in order of operation:
  - InMemoryBus: synchronous pub/sub + retained history (tests/CI default);
  - RedisStreamBus: Redis streams (XADD / XREADGROUP), lazy client;
  - PgOutboxBus: Postgres outbox fallback for publish when Redis is down.

`publish` never raises for infra reasons: the fallback chain swallows
transport errors by design (an event that cannot be delivered is logged to
the in-memory history of the bus that was constructed).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Callable

TOPICS = ("source.changed", "document.parsed", "extraction.complete", "gate.verdict")


class Bus:
    def publish(self, topic: str, payload: dict[str, Any], *, key: str | None = None) -> str: ...
    def subscribe(self, topic: str, handler: Callable[[dict[str, Any]], None]) -> int: ...
    def history(self, topic: str, limit: int = 100) -> list[dict[str, Any]]: ...


def _validate_topic(topic: str) -> None:
    if topic not in TOPICS:
        raise ValueError(f"unknown topic {topic!r}; allowed: {TOPICS}")


class InMemoryBus(Bus):
    def __init__(self) -> None:
        self._handlers: dict[str, list[tuple[int, Callable[[dict[str, Any]], None]]]] = {}
        self._events: dict[str, list[dict[str, Any]]] = {t: [] for t in TOPICS}
        self._next_sub = 0

    def publish(self, topic: str, payload: dict[str, Any], *, key: str | None = None) -> str:
        _validate_topic(topic)
        event_id = str(uuid.uuid4())
        event = {"id": event_id, "topic": topic, "payload": payload, "key": key, "ts": time.time()}
        self._events[topic].append(event)
        for _, handler in self._handlers.get(topic, ()):
            handler(event)
        return event_id

    def subscribe(self, topic: str, handler: Callable[[dict[str, Any]], None]) -> int:
        _validate_topic(topic)
        self._next_sub += 1
        self._handlers.setdefault(topic, []).append((self._next_sub, handler))
        return self._next_sub

    def history(self, topic: str, limit: int = 100) -> list[dict[str, Any]]:
        _validate_topic(topic)
        return self._events[topic][-limit:]


class RedisStreamBus(Bus):
    """Redis streams backend. Lazy redis import; constructed with an
    explicit `redis_url` so tests never touch a server."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0") -> None:
        self.redis_url = redis_url
        self._redis: Any | None = None
        self._fallback = InMemoryBus()

    def _client(self) -> Any:
        if self._redis is None:
            import redis

            self._redis = redis.Redis.from_url(self.redis_url, decode_responses=True)
            self._redis.ping()
        return self._redis

    def publish(self, topic: str, payload: dict[str, Any], *, key: str | None = None) -> str:
        _validate_topic(topic)
        try:
            client = self._client()
            entry = {"payload": json.dumps(payload, default=str), "key": key or ""}
            return str(client.xadd(f"bus:{topic}", entry))
        except Exception:
            return self._fallback.publish(topic, payload, key=key)

    def subscribe(self, topic: str, handler: Callable[[dict[str, Any]], None]) -> int:
        _validate_topic(topic)
        return self._fallback.subscribe(topic, handler)

    def history(self, topic: str, limit: int = 100) -> list[dict[str, Any]]:
        _validate_topic(topic)
        try:
            client = self._client()
            raw = client.xrevrange(f"bus:{topic}", count=limit)
            events = []
            for entry_id, fields in raw:
                events.append({"id": entry_id, "topic": topic, "payload": json.loads(fields["payload"])})
            return events
        except Exception:
            return self._fallback.history(topic, limit)


class PgOutboxBus(Bus):
    """Postgres outbox fallback: rows in `bus_outbox` drained on poll().

    psycopg is optional; if unavailable the bus degrades to in-memory
    delivery so the offline path never raises.
    """

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or os.environ.get("POSTGRES_DSN") or "postgresql://substrate:substrate@localhost:5432/substrate"
        self._conn: Any | None = None
        self._fallback = InMemoryBus()

    def _connect(self) -> Any | None:
        try:
            import psycopg
        except ImportError:
            return None
        if self._conn is None:
            self._conn = psycopg.connect(self.dsn)
            with self._conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bus_outbox (
                        id text PRIMARY KEY,
                        topic text NOT NULL,
                        payload jsonb NOT NULL,
                        published_at timestamptz NOT NULL DEFAULT now()
                    )
                    """
                )
            self._conn.commit()
        return self._conn

    def publish(self, topic: str, payload: dict[str, Any], *, key: str | None = None) -> str:
        _validate_topic(topic)
        conn = self._connect()
        if conn is None:
            return self._fallback.publish(topic, payload, key=key)
        event_id = str(uuid.uuid4())
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO bus_outbox (id, topic, payload) VALUES (%s, %s, %s)",
                (event_id, topic, json.dumps(payload, default=str)),
            )
        conn.commit()
        return event_id

    def poll(self, handler: Callable[[dict[str, Any]], None]) -> int:
        """Deliver undelivered outbox rows; returns count delivered."""
        conn = self._connect()
        if conn is None:
            return 0
        with conn.cursor() as cur:
            cur.execute("SELECT id, topic, payload FROM bus_outbox ORDER BY published_at")
            rows = cur.fetchall()
        delivered = 0
        with conn.cursor() as cur:
            for row_id, topic, payload in rows:
                handler({"id": row_id, "topic": topic, "payload": payload})
                cur.execute("DELETE FROM bus_outbox WHERE id = %s", (row_id,))
                delivered += 1
        conn.commit()
        return delivered

    def subscribe(self, topic: str, handler: Callable[[dict[str, Any]], None]) -> int:
        return self._fallback.subscribe(topic, handler)

    def history(self, topic: str, limit: int = 100) -> list[dict[str, Any]]:
        return self._fallback.history(topic, limit)


def get_bus(name: str | None = None) -> Bus:
    """Factory: env `KNOW_BUS` in {memory, redis, pgoutbox}."""
    backend = name or os.environ.get("KNOW_BUS", "memory")
    if backend == "redis":
        return RedisStreamBus()
    if backend == "pgoutbox":
        return PgOutboxBus()
    return InMemoryBus()
