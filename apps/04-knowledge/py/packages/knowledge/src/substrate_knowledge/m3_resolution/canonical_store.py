"""A-K-15 canonicalization-store.

Canonical ids, alias map, merge audit, source refs. Backed by the generic
KV Store: in-memory for tests, Postgres under compose.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from substrate_knowledge.core.storage import Store
from substrate_knowledge.m3_resolution.blocker import EntityRecord, canonical_name


class CanonicalizationStore:
    def __init__(self, store: Store) -> None:
        self.store = store

    # ------------------------------------------------------------------
    def create_canonical(self, record: EntityRecord, *, audited_by: str = "system") -> str:
        canonical_id = f"can:{uuid.uuid4().hex[:12]}"
        self.store.put(
            canonical_id,
            {
                "canonical_id": canonical_id,
                "name": record.name,
                "type": record.type,
                "source_refs": [record.source],
                "aliases": [canonical_name(record.name)],
                "created_at": time.time(),
            },
        )
        self.store.put(f"alias:{canonical_name(record.name)}", {"canonical_id": canonical_id, "name": record.name})
        self._audit("create", canonical_id, None, record.entity_id, audited_by, {})
        return canonical_id

    def merge(self, canonical_id: str, alias_name: str, record: EntityRecord | None = None, *, audited_by: str = "human") -> str:
        """Attach `alias_name` (and optionally a source ref) to a canonical."""
        canonical = self.store.get(canonical_id)
        if canonical is None:
            raise KeyError(f"unknown canonical {canonical_id}")
        aliases = list(canonical.get("aliases", []))
        alias_key = canonical_name(alias_name)
        if alias_key not in aliases:
            aliases.append(alias_key)
        if record is not None and record.source not in canonical.get("source_refs", []):
            source_refs = list(canonical.get("source_refs", []))
            source_refs.append(record.source)
            canonical["source_refs"] = source_refs
        canonical["aliases"] = aliases
        canonical["name"] = canonical.get("name") or alias_name
        self.store.put(canonical_id, canonical)
        self.store.put(f"alias:{alias_key}", {"canonical_id": canonical_id, "name": alias_name})
        self._audit(
            "merge",
            canonical_id,
            alias_name,
            record.entity_id if record else None,
            audited_by,
            {"source_ref": record.source if record else None},
        )
        return canonical_id

    # ------------------------------------------------------------------
    def resolve_alias(self, name: str) -> str | None:
        entry = self.store.get(f"alias:{canonical_name(name)}")
        return entry.get("canonical_id") if entry else None

    def aliases(self, canonical_id: str) -> list[str]:
        canonical = self.store.get(canonical_id)
        return list(canonical.get("aliases", [])) if canonical else []

    def source_refs(self, canonical_id: str) -> list[str]:
        canonical = self.store.get(canonical_id)
        return list(canonical.get("source_refs", [])) if canonical else []

    def canonical(self, canonical_id: str) -> dict[str, Any] | None:
        return self.store.get(canonical_id)

    def audit(self) -> list[dict[str, Any]]:
        return [value for _, value in self.store.scan("canonical:audit:")]

    def _audit(self, action: str, canonical_id: str, alias: str | None, entity_id: str | None, audited_by: str, extra: dict) -> None:
        key = f"canonical:audit:{uuid.uuid4().hex[:12]}"
        self.store.put(
            key,
            {
                "action": action,
                "canonical_id": canonical_id,
                "alias": alias,
                "entity_id": entity_id,
                "audited_by": audited_by,
                "ts": time.time(),
                **extra,
            },
        )
