"""C1 event-log adapter — the interlock from 04 into 01's event log.

Emits a `stream`-family StoredEvent with the C3 verdict payload, chain hash
and idempotency key, byte-compatible with `@substrate/substrate`'s
`canonicalJson`/`idempotencyKey` conventions so 01 can ingest without forks.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

IDEMPOTENCY_SEP = ":"


def canonical_json(value: Any) -> str:
    """Canonical JSON: stable key ordering (sorted recursively) + no whitespace."""
    if value is None or not isinstance(value, (dict, list)):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ",".join(canonical_json(v) for v in value) + "]"
    obj: dict[str, Any] = value
    keys = sorted(obj)
    return "{" + ",".join(
        f"{json.dumps(k)}:{canonical_json(obj[k])}" for k in keys
    ) + "}"


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


IDEMPOTENCY_SEP = ":"


def idempotency_key(run_id: str, tool_call_id: str, attempt: int) -> str:
    return f"{run_id}{IDEMPOTENCY_SEP}{tool_call_id}{IDEMPOTENCY_SEP}{attempt}"


def chain_hash(prev: str | None, event: dict[str, Any]) -> str:
    return sha256_hex(canonical_json({"prev": prev, "event": event}))


def to_c1_stream_event(
    claim: str,
    verdict: dict[str, Any],
    run_id: str,
    tool_call_id: str,
    attempt: int = 0,
    prev_chain_hash: str | None = None,
) -> dict[str, Any]:
    """Build a C1 `stream` StoredEvent carrying a C3 retrieval verdict."""
    payload = {
        "claim": claim,
        "kind": verdict["kind"],
        "prob": verdict["prob"],
        "citedEvidence": verdict.get("citedEvidence"),
    }
    base: dict[str, Any] = {"family": "stream", "kind": "retrieval.verdict", "payload": payload}
    wrapped = {
        **base,
        "runId": run_id,
        "seq": 0,
        "idempotencyKey": idempotency_key(run_id, tool_call_id, attempt),
        "chainHash": "",
        "ts": "",
    }
    wrapped["chainHash"] = chain_hash(prev_chain_hash, base)
    return wrapped