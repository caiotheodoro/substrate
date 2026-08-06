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

    def delay(args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "data": {"delayed_ms": int(args.get("ms", 0))}}

    def httpbin(args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "data": {"method": args.get("method", "GET"), "path": args.get("path", "/")}}

    def sum_tool(args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "data": {"sum": int(args.get("a", 0)) + int(args.get("b", 0))}}

    def concat_tool(args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "data": {"joined": str(args.get("left", "")) + str(args.get("right", ""))}}

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
        ToolSpec(
            name="delay",
            description="Sleep for a number of milliseconds.",
            input_schema={"type": "object", "properties": {"ms": {"type": "integer"}}, "required": ["ms"]},
            run=delay,
        ),
        ToolSpec(
            name="httpbin",
            description="Simulate an HTTP request.",
            input_schema={
                "type": "object",
                "properties": {"method": {"type": "string"}, "path": {"type": "string"}},
            },
            run=httpbin,
        ),
        ToolSpec(
            name="sum",
            description="Add two integers.",
            input_schema={
                "type": "object",
                "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                "required": ["a", "b"],
            },
            run=sum_tool,
        ),
        ToolSpec(
            name="concat",
            description="Concatenate two strings.",
            input_schema={
                "type": "object",
                "properties": {"left": {"type": "string"}, "right": {"type": "string"}},
                "required": ["left", "right"],
            },
            run=concat_tool,
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

    Task design principles (ARC-AGI-3 §3.4):
    - the prompt embeds the actual required args, so a prompt-reading
      solver (greedy, LLM) CAN succeed — difficulty comes from
      composition, not obscurity;
    - tool sequences are diverse (permutation-based, no repeats) so the
      novelty/structural-OOD checks are meaningful;
    - difficulty prior derives from trajectory length + arg richness
      (calibration replaces this later).
    """

    def __init__(self, tools: list[ToolSpec] | None = None) -> None:
        self.tools = tools or mirror_mock_tools()
        self._by_name = {t.name: t for t in self.tools}

    def _task(self, index: int, calls: list[ToolCall], template: str) -> ForgeTask:
        task_id = _task_id(f"tooluse-{index}-{template}")
        call_desc = "; ".join(
            f"{c.name}({', '.join(f'{k}={v}' for k, v in c.args.items())})" for c in calls
        )
        prompt = template.format(calls=call_desc)
        tools = tuple(self._by_name[c.name] for c in calls)
        # difficulty prior is a function of task features (more calls +
        # richer args = harder) so the calibration model can recover it;
        # rescaled to span ~0.15..0.95 across the sequence space
        # (ARC: most candidates are rejected as too hard/trivial).
        feature_score = len(calls) * 0.18 + sum(len(c.args) for c in calls) * 0.12
        jitter = ((index * 17) % 13) / 100.0  # small deterministic spread
        difficulty = max(0.15, min(0.95, 0.08 + feature_score * 0.32 + jitter))
        return ForgeTask(
            task_id=task_id,
            prompt=prompt,
            tools=tools,
            expected=tuple(calls),
            verifier=_exact_verifier(tuple(calls)),
            difficulty_seed=difficulty,
            metadata={"kind": "tool-use", "generator": "ToolUseTaskGenerator"},
        )

    def _calls_for(self, i: int) -> list[ToolCall]:
        """Diverse, non-repeating tool sequences with per-call args. With 8
        tools and lengths 1..5 the sequence space is large enough for real
        difficulty bandwidth (ARC-AGI-3: multiple mechanics + composition)."""
        import itertools

        tool_names = ["echo", "fake-clock", "file", "fail-once", "delay", "httpbin", "sum", "concat"]
        # deterministic pseudo-random per-index sequence (no repeats within)
        rng_state = (i * 2654435761) & 0xFFFFFFFF
        pool = list(tool_names)
        seq: list[str] = []
        length = 2 + (i % 4)  # 2..5 calls
        while len(seq) < length and pool:
            rng_state = (rng_state * 1103515245 + 12345) & 0x7FFFFFFF
            idx = rng_state % len(pool)
            seq.append(pool.pop(idx))
        calls: list[ToolCall] = []
        for j, name in enumerate(seq):
            if name == "echo":
                args = {"text": f"payload-{i}-{j}"}
            elif name == "fake-clock":
                args = {"set": f"2026-01-01T00:00:0{i % 10}.000Z"}
            elif name == "file":
                args = {"path": f"/tmp/f{i}.txt", "content": f"content-{i}-{j}"}
            elif name == "fail-once":
                args = {"label": f"op-{i}"}
            elif name == "delay":
                args = {"ms": (i * 7 + j * 3) % 100}
            elif name == "httpbin":
                args = {"method": "GET", "path": f"/api/{i}"}
            elif name == "sum":
                args = {"a": i % 10, "b": j}
            else:  # concat
                args = {"left": f"L{i}", "right": f"R{j}"}
            calls.append(ToolCall(name=name, args=args))
        return calls

    def generate(self, n: int = 20) -> list[ForgeTask]:
        templates = [
            "Call the tools exactly as follows, in order: {calls}. Do nothing else.",
            "Perform exactly these steps, in order: {calls}.",
            "Execute this sequence precisely: {calls}.",
        ]
        tasks: list[ForgeTask] = []
        for i in range(n):
            template = templates[i % len(templates)]
            tasks.append(self._task(i, self._calls_for(i), template))
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


class DerivedArgTaskGenerator:
    """Compositional-difficulty axis: the prompt names the tools and the
    RULE for the args, but the exact values must be DERIVED (e.g. "echo the
    length of the word 'banana'"). A prompt-following greedy solver fails;
    only a reasoning agent (or the perfect solver) succeeds. This is the
    ARC-AGI-3 'difficulty through composition' principle."""

    def __init__(self, tools: list[ToolSpec] | None = None) -> None:
        self.tools = tools or mirror_mock_tools()
        self._by_name = {t.name: t for t in self.tools}

    def _task(self, index: int, word: str, template: str) -> ForgeTask:
        task_id = _task_id(f"derived-{index}-{word}")
        expected_len = len(word)
        prompt = template.format(word=word, length=expected_len)
        calls = (ToolCall(name="echo", args={"text": str(expected_len)}),)
        tools = (self._by_name["echo"],)
        difficulty = 0.55 + 0.3 * (index % 3) / 2.0
        return ForgeTask(
            task_id=task_id,
            prompt=prompt,
            tools=tools,
            expected=calls,
            verifier=_exact_verifier(calls),
            difficulty_seed=difficulty,
            metadata={"kind": "tool-use", "generator": "DerivedArgTaskGenerator"},
        )

    def generate(self, n: int = 10) -> list[ForgeTask]:
        words = ["banana", "strawberry", "watermelon", "elephant", "keyboard", "mountain", "university", "pineapple"]
        templates = [
            "Call echo with the length of the word '{word}'. The answer is {length}.",
            "Use echo to report how many letters are in '{word}'. It has {length}.",
        ]
        tasks: list[ForgeTask] = []
        for i in range(n):
            template = templates[i % len(templates)]
            tasks.append(self._task(i, words[i % len(words)], template))
        return tasks
