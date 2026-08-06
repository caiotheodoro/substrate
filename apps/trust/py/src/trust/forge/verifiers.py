"""Programmatic verifiers (P1). Judges never score answers; every task's
ground truth is a deterministic verifier over the recorded trajectory.
"""
from __future__ import annotations

from typing import Any, Callable

from trust.forge.task import ForgeTask, ToolCall


def exact_trajectory_verifier(expected: tuple[ToolCall, ...]) -> Callable[[list[dict[str, Any]]], bool]:
    """Byte-exact trajectory match (harness golden-replay discipline)."""

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


def reference_run_verifier(task: ForgeTask) -> Callable[[list[dict[str, Any]]], bool]:
    """Runs the expected trajectory through the tool registry offline and
    verifies the recorded results match the reference run. This is the
    'executable ground truth' — a verifier that doesn't depend on string
    formatting, only on tool semantics."""

    def run(tools: tuple, calls: tuple[ToolCall, ...]) -> list[dict[str, Any]]:
        by_name = {t.name: t for t in tools}
        out: list[dict[str, Any]] = []
        for call in calls:
            tool = by_name[call.name]
            out.append({"name": call.name, "args": call.args, "result": tool(call.args)})
        return out

    reference = run(task.tools, task.expected)

    def verify(trajectory: list[dict[str, Any]]) -> bool:
        if len(trajectory) != len(reference):
            return False
        for step, ref in zip(trajectory, reference):
            if step.get("name") != ref["name"]:
                return False
            if step.get("args") != ref["args"]:
                return False
            if step.get("result") != ref["result"]:
                return False
        return True

    return verify


def args_property_verifier(
    name: str,
    check: Callable[[dict[str, Any]], bool],
) -> Callable[[list[dict[str, Any]]], bool]:
    """Weak verifier: some tool was called with args satisfying a property."""

    def verify(trajectory: list[dict[str, Any]]) -> bool:
        return any(step.get("name") == name and check(step.get("args") or {}) for step in trajectory)

    return verify


def property_verifier(
    check: Callable[[list[dict[str, Any]]], bool],
) -> Callable[[list[dict[str, Any]]], bool]:
    """Fully custom verifier."""
    return check
