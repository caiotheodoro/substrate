"""Forge task model (P1: verifiable domains only).

A ``ForgeTask`` is a self-contained, verifiable agent task: a prompt, a
tool registry (Python mirror of the harness mock tools), the expected
trajectory (ordered tool calls + args), and a programmatic verifier.

Every task MUST have a passing verifier before it enters the gauntlet —
the verifier is the ground truth; judges are never used to score answers.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


class Tool(Protocol):
    name: str
    description: str
    input_schema: dict[str, Any]

    def run(self, args: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ToolSpec:
    """Python mirror of the harness ``ToolSpec`` (json-schema args)."""

    name: str
    description: str
    input_schema: dict[str, Any]
    run: Callable[[dict[str, Any]], dict[str, Any]]

    def __call__(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.run(args)


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ForgeTask:
    task_id: str
    prompt: str
    tools: tuple[ToolSpec, ...]
    expected: tuple[ToolCall, ...]
    verifier: Callable[[list[dict[str, Any]]], bool]
    difficulty_seed: float = 0.5  # generator's prior; calibration replaces it
    metadata: dict[str, Any] = field(default_factory=dict)

    def hash(self) -> str:
        payload = {
            "task_id": self.task_id,
            "prompt": self.prompt,
            "tools": [t.name for t in self.tools],
            "expected": [{"name": c.name, "args": c.args} for c in self.expected],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]

    def verify(self, trajectory: list[dict[str, Any]]) -> bool:
        """Run the programmatic verifier over a recorded trajectory."""
        return self.verifier(trajectory)

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "prompt": self.prompt,
            "tools": [t.name for t in self.tools],
            "expected": [{"name": c.name, "args": c.args} for c in self.expected],
            "difficulty_seed": self.difficulty_seed,
            "metadata": self.metadata,
            "hash": self.hash(),
        }


def canonical_trajectory(trajectory: list[dict[str, Any]]) -> str:
    """Byte-stable trajectory for exact-match verification (ties into the
    harness golden-replay byte-identity discipline)."""
    return json.dumps(trajectory, sort_keys=True, separators=(",", ":"))
