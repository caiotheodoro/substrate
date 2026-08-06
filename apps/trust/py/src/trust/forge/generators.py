"""Task generators (P1: verifiable domains only).

V1 generators build tool-use tasks over a Python mirror of the harness
mock-tool registry. Each generated task carries a programmatic verifier
(exact trajectory match or a weaker args/property check) so it can enter
the gauntlet without any LLM involvement.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from trust.forge.task import ForgeTask, ToolCall, ToolSpec, canonical_trajectory


def mirror_mock_tools() -> list[ToolSpec]:
    """Python mirror of the harness mock tools (deterministic, offline)."""

    def echo(args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "data": {"echoed": args.get("text", "")}}

    def fake_clock(args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "data": {"now": args.get("set", "2026-01-01T00:00:00.000Z")}}

    def file_write(args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "data": {"path": args.get("path", ""), "bytes": len(str(args.get("content", "")))}}

    def fail_once(args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "data": {"label": args.get("label", "op"), "attempt": 2}}

    return [
        ToolSpec(
            name="echo",
            description="Echo the given text back.",
            input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
            run=echo,
        ),
        ToolSpec(
            name="fake-clock",
            description="Return the current time, optionally set it.",
            input_schema={"type": "object", "properties": {"set": {"type": "string"}}},
            run=fake_clock,
        ),
        ToolSpec(
            name="file",
            description="Write content to a virtual file.",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path"],
            },
            run=file_write,
        ),
        ToolSpec(
            name="fail-once",
            description="Fail on the first call, succeed afterwards.",
            input_schema={"type": "object", "properties": {"label": {"type": "string"}}},
            run=fail_once,
        ),
    ]


def _task_id(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()[:12]


def _exact_verifier(expected: tuple[ToolCall, ...]):
    """Byte-exact trajectory verifier (the harness golden discipline)."""

    def verify(trajectory: list[dict[str, Any]]) -> bool:
        if len(trajectory) != len(expected):
            return False
        for step, call in zip(trajectory, expected):
            if step.get("name") != call.name:
                return False
            if step.get("args") != call.args:
                return False
        return True

    return verify


def _any_order_verifier(expected: tuple[ToolCall, ...]):
    """Order-insensitive verifier: the multiset of calls must match."""

    def verify(trajectory: list[dict[str, Any]]) -> bool:
        got = [(s.get("name"), s.get("args")) for s in trajectory]
        want = [(c.name, c.args) for c in expected]
        return sorted(got, key=str) == sorted(want, key=str)

    return verify


class ToolUseTaskGenerator:
    """Generates tool-use tasks over the mirrored registry.

    ``n`` tasks are built from a cartesian product of prompt templates and
    expected trajectories, each with a difficulty prior derived from
    trajectory length (longer = harder — calibration replaces this later).
    """

    def __init__(self, tools: list[ToolSpec] | None = None) -> None:
        self.tools = tools or mirror_mock_tools()
        self._by_name = {t.name: t for t in self.tools}

    def _task(self, index: int, calls: list[ToolCall], template: str) -> ForgeTask:
        task_id = _task_id(f"tooluse-{index}-{template}")
        prompt = template.format(calls=" -> ".join(c.name for c in calls))
        tools = tuple(self._by_name[c.name] for c in calls)
        # difficulty prior is a function of task features (more calls +
        # richer args = harder) so the calibration model can recover it;
        # spans the full range (ARC: most candidates are rejected as too
        # hard/trivial). Calibration replaces this prior.
        feature_score = len(calls) * 0.18 + sum(len(c.args) for c in calls) * 0.12
        jitter = ((index * 17) % 13) / 100.0  # small deterministic spread
        difficulty = max(0.1, min(0.95, 0.1 + feature_score + jitter))
        return ForgeTask(
            task_id=task_id,
            prompt=prompt,
            tools=tools,
            expected=tuple(calls),
            verifier=_exact_verifier(tuple(calls)),
            difficulty_seed=difficulty,
            metadata={"kind": "tool-use", "generator": "ToolUseTaskGenerator"},
        )

    def generate(self, n: int = 20) -> list[ForgeTask]:
        templates = [
            "Call the tools in this order: {calls}. Do nothing else.",
            "Perform exactly these steps, in order: {calls}.",
        ]
        tasks: list[ForgeTask] = []
        for i in range(n):
            template = templates[i % len(templates)]
            length = 1 + (i % 3)  # 1..3 calls
            names = ["echo", "fake-clock", "file", "fail-once"]
            calls: list[ToolCall] = []
            for j in range(length):
                name = names[(i + j) % len(names)]
                args = {"text": f"payload-{i}-{j}"} if name == "echo" else (
                    {"set": f"2026-01-01T00:00:0{i % 10}.000Z"} if name == "fake-clock" else (
                        {"path": f"/tmp/f{i}.txt", "content": f"content-{i}-{j}"} if name == "file" else {"label": f"op-{i}"}
                    )
                )
                calls.append(ToolCall(name=name, args=args))
            tasks.append(self._task(i, calls, template))
        return tasks


class AmbiguousTaskGenerator:
    """Generates tasks whose verifier is intentionally order-insensitive —
    a distinct difficulty axis (the agent may choose any valid order)."""

    def __init__(self, tools: list[ToolSpec] | None = None) -> None:
        self.tools = tools or mirror_mock_tools()
        self._by_name = {t.name: t for t in self.tools}

    def generate(self, n: int = 8) -> list[ForgeTask]:
        tasks: list[ForgeTask] = []
        for i in range(n):
            calls = [
                ToolCall(name="echo", args={"text": f"a-{i}"}),
                ToolCall(name="file", args={"path": f"/tmp/g{i}.txt", "content": "x"}),
            ]
            task_id = _task_id(f"ambig-{i}")
            tools = tuple(self._by_name[c.name] for c in calls)
            tasks.append(
                ForgeTask(
                    task_id=task_id,
                    prompt=f"Write a file and echo a marker, in any order ({i}).",
                    tools=tools,
                    expected=tuple(calls),
                    verifier=_any_order_verifier(tuple(calls)),
                    difficulty_seed=0.5,
                    metadata={"kind": "tool-use", "generator": "AmbiguousTaskGenerator"},
                )
            )
        return tasks
