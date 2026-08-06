"""C1 event-log discipline (mirrors packages/substrate/src/contracts/events.ts).

Canonical JSON = recursively sorted keys, no whitespace. `chain_hash` is the
sha-256 of the canonical (family, kind/payload) chain up to this event —
byte-exact serialization is what makes golden runs and prompt fingerprints
reproducible across languages.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    """Recursively-sorted-key, no-whitespace JSON (byte-exact w/ TS impl)."""
    if value is None or not isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, list):
        return "[" + ",".join(canonical_json(v) for v in value) + "]"
    obj = value
    keys = sorted(obj.keys())
    return "{" + ",".join(
        f"{json.dumps(k, ensure_ascii=False, separators=(',', ':'))}:{canonical_json(obj[k])}"
        for k in keys
    ) + "}"


def chain_hash(prev_hash: str, body: str) -> str:
    """sha-256 of (prev_chain_hash + canonical body). 64 lowercase hex chars."""
    return hashlib.sha256((prev_hash + body).encode("utf-8")).hexdigest()


def idempotency_key(run_id: str, tool_call_id: str, attempt: int) -> str:
    return f"{run_id}:{tool_call_id}:{attempt}"
