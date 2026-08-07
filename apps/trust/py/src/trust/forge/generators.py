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
    """Suffix-exact trajectory verifier: the trajectory's last len(expected)
    steps must byte-match, in order — any leading steps are tolerated as
    wasted/exploratory actions.

    This is deliberately NOT the harness's byte-exact golden-replay
    discipline (that stricter equal-length check lives in
    ``verifiers.exact_trajectory_verifier`` and is used where byte-identical
    replay is the point, e.g. ReproducibilityCheck). Here, "solved" means
    "eventually produced the right sequence" — matching ARC-AGI-3's own
    semantics (a level is won by reaching the goal state via any playthrough,
    not by taking the theoretically shortest one). Tolerating leading waste
    is what makes RHAE's per-level efficiency ratio (human baseline vs agent
    action count) non-degenerate: without it, every successful solve has
    agent_actions == len(expected) by construction, for every solver, and
    the efficiency dimension of the score can never vary."""

    def verify(trajectory: list[dict[str, Any]]) -> bool:
        if len(trajectory) < len(expected):
            return False
        tail = trajectory[len(trajectory) - len(expected):]
        for step, call in zip(tail, expected):
            if step.get("name") != call.name:
                return False
            if step.get("args") != call.args:
                return False
        return True

    return verify


def _any_order_verifier(expected: tuple[ToolCall, ...]):
    """Order-insensitive, suffix-tolerant verifier: the LAST len(expected)
    steps, as a multiset, must match — see ``_exact_verifier`` for why
    leading waste is tolerated."""

    def verify(trajectory: list[dict[str, Any]]) -> bool:
        if len(trajectory) < len(expected):
            return False
        tail = trajectory[len(trajectory) - len(expected):]
        got = [(s.get("name"), s.get("args")) for s in tail]
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
                # full i in the fractional-seconds slot, not i % 10 — the
                # truncated version made any two tasks with i differing by
                # a multiple of 10 emit an identical fake-clock call, which
                # (combined with the other truncated args below) produced
                # real duplicate task signatures once novelty checking
                # actually ran against an accumulating corpus instead of
                # the permanently-empty one it used to see.
                args = {"set": f"2026-01-01T00:00:00.{i:06d}Z"}
            elif name == "file":
                args = {"path": f"/tmp/f{i}.txt", "content": f"content-{i}-{j}"}
            elif name == "fail-once":
                args = {"label": f"op-{i}"}
            elif name == "delay":
                args = {"ms": i * 7 + j * 3}  # was % 100 — same collision reason
            elif name == "httpbin":
                args = {"method": "GET", "path": f"/api/{i}"}
            elif name == "sum":
                args = {"a": i, "b": j}  # was i % 10 — same collision reason
            else:  # concat
                args = {"left": f"L{i}", "right": f"R{j}"}
            calls.append(ToolCall(name=name, args=args))
        return calls

    def generate(self, n: int = 20, *, index_offset: int = 0) -> list[ForgeTask]:
        """``index_offset`` shifts every task's underlying index (task id,
        arg values, difficulty jitter — everything is a pure function of
        the index) into a disjoint range. Used to build a genuinely
        independent reference pool (see
        ``contamination.build_reference_corpus``) that shares no
        incidental structure with a normally-indexed population, so
        matches against it are real collisions, not self-lookups."""
        templates = [
            "Call the tools exactly as follows, in order: {calls}. Do nothing else.",
            "Perform exactly these steps, in order: {calls}.",
            "Execute this sequence precisely: {calls}.",
        ]
        tasks: list[ForgeTask] = []
        for i in range(n):
            idx = index_offset + i
            template = templates[idx % len(templates)]
            tasks.append(self._task(idx, self._calls_for(idx), template))
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
        prompt = template.format(word=word)
        # Two calls, not one: restate the word verbatim, then derive its
        # length. This is what actually makes the task's signature depend
        # on the WORD, not just the numeric answer — with only the length
        # in `expected`, two different words of equal length (e.g.
        # "elephant" and "keyboard", both 8) were structurally
        # indistinguishable (4 unique signatures across 8 generated words),
        # so most of this generator's output was flagged as duplicates the
        # moment novelty checking actually ran against an accumulating
        # corpus, instead of the empty one it used to see.
        calls = (
            ToolCall(name="echo", args={"text": word}),
            ToolCall(name="echo", args={"text": str(expected_len)}),
        )
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
        # 150 distinct words, not 8 — with novelty checking now actually
        # accumulating a corpus (it used to compare against a permanently
        # empty one), a vocabulary smaller than the requested `n` produces
        # genuine repeats: the caller (benchmark.py) typically asks for
        # n_tasks // 4, which comfortably exceeded a smaller word list at
        # benchmark scales in the 300-500 task range this pipeline
        # actually runs at (75-125 derived tasks requested). Words of
        # varying length (4-14 letters) preserve the generator's
        # difficulty-through-composition intent; where `n` still exceeds
        # the vocabulary, repeats are correctly caught by the gauntlet
        # rather than silently accepted, which is the gauntlet doing its
        # job, not a bug to route around.
        words = [
            "banana", "strawberry", "watermelon", "elephant", "keyboard", "mountain",
            "university", "pineapple", "umbrella", "notebook", "sandwich", "telephone",
            "butterfly", "chocolate", "dinosaur", "furniture", "gymnasium", "helicopter",
            "identity", "jellyfish", "kangaroo", "lighthouse", "microscope", "newspaper",
            "orchestra", "penguin", "questionnaire", "raspberry", "skateboard", "telescope",
            "triangle", "volcano", "waterfall", "xylophone", "yesterday", "zeppelin",
            "adventure", "blueberry", "cardboard", "dragonfly", "engineer", "fireplace",
            "greenhouse", "hurricane", "instrument", "junction", "kilometer", "landscape",
            "marathon", "necklace", "obstacle", "paragraph", "quicksand", "restaurant",
            "sunflower", "treasure", "underwater", "vegetable", "wardrobe", "yogurt",
            "airplane", "backpack", "calendar", "daffodil", "eyebrow", "flashlight",
            "gorilla", "hedgehog", "icicle", "jackpot", "knapsack", "lemonade",
            "mushroom", "narwhal", "octopus", "peacock", "quilt", "rainbow",
            "seashell", "tornado", "unicorn", "violin", "walnut", "xerox",
            "yardstick", "zucchini", "avocado", "birthday", "compass", "daylight",
            "elevator", "frisbee", "gadget", "hammock", "igloo", "jungle",
            "kettle", "labyrinth", "mailbox", "nutshell", "onion", "pretzel",
            "quarterly", "rocket", "seahorse", "thermostat", "upstream", "vineyard",
            "windmill", "xylograph", "yearbook", "zamboni", "artichoke", "bumblebee",
            "chandelier", "dumpling", "eggplant", "footprint", "gravity", "hairbrush",
            "impulse", "javelin", "keystone", "lantern", "meadow", "nectarine",
            "oatmeal", "pancake", "quokka", "riverbank", "seaweed", "tumbleweed",
            "utensil", "velvet", "whistle", "yolk", "zipper", "anchor",
            "biscuit", "cactus", "doorway", "envelope", "fountain", "goggles",
            "harmony", "invoice", "jigsaw", "knuckle", "lumber", "moonlight",
            "nightfall", "outpost", "pyramid", "quiver", "ribbon", "spatula",
            "adventure", "blueberry", "cardboard", "dragonfly",
        ]
        # No plaintext answer in the prompt (a prior version said "The
        # answer is {length}" — trivially readable by a real LLM, defeating
        # the entire "derive, don't read off" premise; a regex-based
        # GreedySolver never exploited it since it only matches
        # `tool(key=value)` parenthesis syntax, but a real reasoning model
        # absolutely would, silently making this difficulty axis fake for
        # exactly the solver it's meant to test).
        templates = [
            "First call echo with the word '{word}' verbatim. Then call echo again with the number of letters in '{word}' — compute it, it is not stated here.",
            "Restate '{word}' via echo. Then, separately, echo how many letters '{word}' contains. You must count; the length is not given.",
        ]
        tasks: list[ForgeTask] = []
        for i in range(n):
            template = templates[i % len(templates)]
            tasks.append(self._task(i, words[i % len(words)], template))
        return tasks
