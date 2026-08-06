"""A-S-30 social-log: post/reply/lurk/silence/alliance → C1 event format.

Every record is a C1 `stream` event with the StoredEvent envelope: runId,
monotonic seq, unique idempotencyKey, sha-256 chainHash over canonical JSON
(mirroring packages/substrate/src/contracts/events.ts), ts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from sim_shared.canonical import canonical_json, chain_hash

EVENT_KINDS = ("post", "reply", "lurk", "silence", "alliance", "join", "leave")


@dataclass
class C1StreamEvent:
    run_id: str
    seq: int
    idempotency_key: str
    chain_hash: str
    ts: str
    kind: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": "stream",
            "kind": self.kind,
            "payload": self.payload,
            "runId": self.run_id,
            "seq": self.seq,
            "idempotencyKey": self.idempotency_key,
            "chainHash": self.chain_hash,
            "ts": self.ts,
        }


class SocialLog:
    """Append-only JSONL stream in C1 format."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self._buffer: list[C1StreamEvent] = []
        self._seq = 0
        self._chain = "0" * 64
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists():
                for ev in self._read_existing():
                    self._buffer.append(ev)
                    self._seq = max(self._seq, ev.seq)
                    self._chain = ev.chain_hash

    def _read_existing(self) -> Iterator[C1StreamEvent]:
        for line in self.path.read_text().splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            yield C1StreamEvent(
                run_id=raw["runId"],
                seq=raw["seq"],
                idempotency_key=raw["idempotencyKey"],
                chain_hash=raw["chainHash"],
                ts=raw["ts"],
                kind=raw["kind"],
                payload=raw["payload"],
            )

    def write(self, run_id: str, kind: str, payload: dict[str, Any], t: int | None = None) -> C1StreamEvent:
        if kind not in EVENT_KINDS:
            raise ValueError(f"unknown social-log kind: {kind}")
        self._seq += 1
        body = canonical_json({"kind": kind, "payload": payload})
        ch = chain_hash(self._chain, body)
        ev = C1StreamEvent(
            run_id=run_id,
            seq=self._seq,
            idempotency_key=f"{run_id}:{kind}:{self._seq}",
            chain_hash=ch,
            ts=f"t={t if t is not None else self._seq}",
            kind=kind,
            payload=payload,
        )
        self._buffer.append(ev)
        self._chain = ch
        if self.path:
            with self.path.open("a") as f:
                f.write(json.dumps(ev.to_dict()) + "\n")
        return ev

    def events(self) -> list[C1StreamEvent]:
        return list(self._buffer)

    def to_c1(self) -> list[dict[str, Any]]:
        return [ev.to_dict() for ev in self._buffer]

    def chain_integrity(self) -> bool:
        """Re-verify the whole chain from genesis."""
        prev = "0" * 64
        for ev in self._buffer:
            body = canonical_json({"kind": ev.kind, "payload": ev.payload})
            if ev.chain_hash != chain_hash(prev, body):
                return False
            prev = ev.chain_hash
        return True