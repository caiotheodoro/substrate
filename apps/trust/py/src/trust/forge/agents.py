"""Agent harness — real solvers that run forge tasks and produce action
counts + trajectories. These are the "systems" the benchmark scores.

Solvers:
- RandomSolver: draws tool calls uniformly (the brute-force baseline;
  ARC-AGI-3's random-policy floor says it must fail).
- GreedySolver: reads the prompt, calls tools in the order named in it
  (a weak but non-random system).
- PerfectSolver: emits the expected trajectory with zero wasted actions
  (the upper bound; scores ~1.0 by construction).
- LlmSolver: OpenAI-compatible bridge (Ollama / any :v1 endpoint) —
  the real frontier-style system; offline by default.

Every solver returns (trajectory, n_actions). The harness enforces the
5x-human action budget: an agent that exceeds it is terminated and the
level scores 0 for that level.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from trust.forge.task import ForgeTask


@dataclass
class AgentRun:
    solver: str
    task_id: str
    trajectory: list[dict[str, Any]] = field(default_factory=list)
    n_actions: int = 0
    terminated: bool = False  # hit the action budget
    solved: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "solver": self.solver,
            "task_id": self.task_id,
            "n_actions": self.n_actions,
            "terminated": self.terminated,
            "solved": self.solved,
        }


class Solver(Protocol):
    name: str

    def solve(self, task: ForgeTask, budget: int) -> AgentRun: ...


class RandomSolver:
    """Uniform random tool calls — the brute-force baseline."""

    name = "random"

    def __init__(self, seed: int = 0) -> None:
        self.seed = seed

    def solve(self, task: ForgeTask, budget: int) -> AgentRun:
        rng = random.Random(f"{self.seed}:{task.task_id}")
        by_name = {t.name: t for t in task.tools}
        names = list(by_name)
        trajectory: list[dict[str, Any]] = []
        solved = False
        for step in range(budget):
            name = rng.choice(names)
            args = {k: f"x{step}" for k in by_name[name].input_schema.get("properties", {})}
            try:
                result = by_name[name](args)
            except Exception:
                result = {"ok": False, "error": "crash"}
            trajectory.append({"name": name, "args": args, "result": result})
            if task.verify(trajectory):
                solved = True
                break
        return AgentRun(
            solver=self.name,
            task_id=task.task_id,
            trajectory=trajectory,
            n_actions=len(trajectory),
            terminated=not solved and len(trajectory) >= budget,
            solved=solved,
        )


class GreedySolver:
    """Parses tool calls (name + key=value args) out of the prompt and
    executes them in order — a weak but informed system (prompt-following,
    no reasoning). Because task prompts embed the required args, greedy CAN
    solve the easy tasks but fails as sequences/composition grow."""

    name = "greedy"

    def solve(self, task: ForgeTask, budget: int) -> AgentRun:
        by_name = {t.name: t for t in task.tools}
        calls = _parse_prompt_calls(task.prompt, set(by_name))
        trajectory: list[dict[str, Any]] = []
        solved = False
        for step in range(budget):
            if step >= len(calls):
                break
            name, args = calls[step]
            if name not in by_name:
                break
            try:
                result = by_name[name](args)
            except Exception:
                result = {"ok": False, "error": "crash"}
            trajectory.append({"name": name, "args": args, "result": result})
            if task.verify(trajectory):
                solved = True
                break
        return AgentRun(
            solver=self.name,
            task_id=task.task_id,
            trajectory=trajectory,
            n_actions=len(trajectory),
            terminated=not solved and len(trajectory) >= budget,
            solved=solved,
        )


def _parse_prompt_calls(prompt: str, tool_names: set[str]) -> list[tuple[str, dict[str, Any]]]:
    """Parse 'tool(key=value, key=value)' calls out of the prompt text."""
    calls: list[tuple[str, dict[str, Any]]] = []
    for match in re.finditer(r"(\w[\w-]*)\(([^)]*)\)", prompt):
        name = match.group(1)
        if name not in tool_names:
            continue
        args: dict[str, Any] = {}
        for kv in match.group(2).split(","):
            kv = kv.strip()
            if "=" not in kv:
                continue
            k, v = kv.split("=", 1)
            v = v.strip().strip('"').strip("'")
            if v == "True":
                v = True
            elif v == "False":
                v = False
            args[k.strip()] = v
        calls.append((name, args))
    return calls


class PerfectSolver:
    """Emits the expected trajectory exactly — the upper bound (1.0 by
    construction; validates the scoring math)."""

    name = "perfect"

    def solve(self, task: ForgeTask, budget: int) -> AgentRun:
        by_name = {t.name: t for t in task.tools}
        trajectory: list[dict[str, Any]] = []
        for call in task.expected:
            try:
                result = by_name[call.name](call.args)
            except Exception:
                result = {"ok": False, "error": "crash"}
            trajectory.append({"name": call.name, "args": call.args, "result": result})
        return AgentRun(
            solver=self.name,
            task_id=task.task_id,
            trajectory=trajectory,
            n_actions=len(trajectory),
            terminated=False,
            solved=task.verify(trajectory),
        )


class LlmSolver:
    """OpenAI-compatible bridge (Ollama / any :v1 endpoint). The real
    frontier-style system. Offline by default — skips when no endpoint.

    The model sees the task prompt and the available tools, and emits a
    tool call per turn until the task verifies or the budget runs out.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        model: str = "qwen2.5:3b",
        api_key: str = "ollama",
        name: str = "llm",
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.api_key = api_key
        self.name = name

    def solve(self, task: ForgeTask, budget: int) -> AgentRun:
        import json
        import logging

        import httpx

        log = logging.getLogger(__name__)
        trajectory: list[dict[str, Any]] = []
        solved = False
        for step in range(budget):
            tool_desc = "\n".join(f"- {t.name}: {t.description} args={json.dumps(t.input_schema)}" for t in task.tools)
            history = "\n".join(json.dumps(s) for s in trajectory[-4:])
            prompt = (
                f"{task.prompt}\n\nTools:\n{tool_desc}\n\n"
                f"Previous calls:\n{history or '(none)'}\n\n"
                'Emit ONLY a JSON object like {"name": "<tool>", "args": {...}} for the next tool call.'
            )
            # Network/HTTP failures are unrecoverable -- the endpoint
            # itself is the problem, so the episode ends. A hallucinated
            # tool name or malformed JSON response is NOT the same class
            # of failure: a real model can second-guess itself and still
            # land on the right answer next turn. Treating both the same
            # (break immediately) used to mean one bad tool name killed the
            # whole episode instead of costing a single wasted action --
            # the suffix-tolerant verifier (generators._exact_verifier)
            # exists specifically so a trajectory like that can still
            # verify once the agent recovers.
            try:
                resp = httpx.post(
                    f"{self.base_url}/chat/completions",
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0,
                    },
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=60,
                )
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                log.warning("LlmSolver step %d: endpoint failure for task %s (%s): %s", step, task.task_id, self.model, exc)
                break

            try:
                content = resp.json()["choices"][0]["message"]["content"]
                content = content.strip().strip("`")
                if content.startswith("json"):
                    content = content[4:].strip()
                call = json.loads(content)
                name, args = call["name"], call.get("args", {})
                tool = next((t for t in task.tools if t.name == name), None)
                if tool is None:
                    log.warning("LlmSolver step %d: hallucinated tool %r for task %s", step, name, task.task_id)
                    trajectory.append({"name": name, "args": args, "result": {"ok": False, "error": "unknown tool"}})
                    continue
                result = tool(args)
            except Exception as exc:
                log.warning("LlmSolver step %d: malformed response for task %s (%s): %s", step, task.task_id, self.model, exc)
                trajectory.append({"name": "(parse-error)", "args": {}, "result": {"ok": False, "error": str(exc)}})
                continue

            trajectory.append({"name": name, "args": args, "result": result})
            if task.verify(trajectory):
                solved = True
                break
        return AgentRun(
            solver=self.name,
            task_id=task.task_id,
            trajectory=trajectory,
            n_actions=len(trajectory),
            terminated=not solved and len(trajectory) >= budget,
            solved=solved,
        )
