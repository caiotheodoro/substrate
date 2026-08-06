"""A-K-11 blocker — blocking keys for candidate generation.

Canonical name, type, source, date. Splink is the production vehicle; this
is the deterministic offline implementation of the same idea (key hashing
into blocks). A pair of records can only match if they share at least one
blocking key, which bounds the comparison space.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

BLOCKING_KEYS = ("name", "type", "source", "date")


def canonical_name(name: str) -> str:
    """Normalized name: lowercase, keep alnum only, collapse spaces."""
    return re.sub(r"[^a-z0-9]+", "", name.lower())


@dataclass
class EntityRecord:
    entity_id: str
    name: str
    type: str
    source: str = "unknown"
    date: str | None = None

    def key_value(self, key: str) -> str:
        if key == "name":
            return canonical_name(self.name)
        if key == "type":
            return canonical_name(self.type)
        if key == "source":
            return canonical_name(self.source)
        if key == "date":
            return canonical_name(self.date or "")
        raise ValueError(f"unknown blocking key {key!r}")


@dataclass
class Block:
    key: str
    key_type: str
    member_ids: list[str]
    members: list[EntityRecord]


class Blocker:
    """Blocks on every key in `keys`; a record participates in one block per
    key. Empty key values (e.g. missing date) are skipped to avoid a single
    giant block for all records lacking that attribute."""

    def __init__(self, keys: tuple[str, ...] = BLOCKING_KEYS) -> None:
        self.keys = keys

    def block(self, records: list[EntityRecord]) -> list[Block]:
        blocks: dict[tuple[str, str], list[EntityRecord]] = {}
        for record in records:
            for key in self.keys:
                value = record.key_value(key)
                if not value:
                    continue
                blocks.setdefault((key, value), []).append(record)
        result = []
        for (key_type, value), members in sorted(blocks.items()):
            if len(members) < 2:
                continue
            result.append(
                Block(
                    key=value,
                    key_type=key_type,
                    member_ids=[m.entity_id for m in members],
                    members=members,
                )
            )
        return result
