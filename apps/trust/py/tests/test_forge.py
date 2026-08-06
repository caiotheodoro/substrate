"""Phase 1 — the Forge core: generators, verifiers, gauntlet.

Validation gate: ≥95% of generated tasks pass the gauntlet on the default
generator; every planted-bad case is rejected (trivial task, unverifiable
task, non-reproducible task, duplicate task).
"""
from __future__ import annotations

import pytest

from trust.forge.forge import forge_tasks
from trust.forge.gauntlet import (
    FuzzSweep,
    NoveltyCheck,
    RandomPolicyFloor,
    ReproducibilityCheck,
    run_gauntlet,
)
from trust.forge.generators import AmbiguousTaskGenerator, ToolUseTaskGenerator
from trust.forge.task import ForgeTask, ToolCall
from trust.forge.verifiers import exact_trajectory_verifier


class TestGenerators:
    def test_tool_use_generator_produces_valid_tasks(self):
        tasks = ToolUseTaskGenerator().generate(n=20)
        assert len(tasks) == 20
        for t in tasks:
            assert t.expected
            assert t.hash()
            assert t.difficulty_seed > 0

    def test_reference_trajectory_verifies(self):
        tasks = ToolUseTaskGenerator().generate(n=20)
        for t in tasks:
            by_name = {tool.name: tool for tool in t.tools}
            trajectory = [{"name": c.name, "args": c.args, "result": by_name[c.name](c.args)} for c in t.expected]
            assert t.verify(trajectory), t.task_id

    def test_ambiguous_generator_accepts_any_order(self):
        tasks = AmbiguousTaskGenerator().generate(n=8)
        for t in tasks:
            # reversed order still verifies
            reversed_traj = [{"name": c.name, "args": c.args} for c in reversed(t.expected)]
            assert t.verify(reversed_traj)


class TestVerifiers:
    def test_exact_verifier_rejects_wrong_order(self):
        calls = (ToolCall(name="echo", args={"text": "a"}), ToolCall(name="file", args={"path": "/x", "content": "y"}))
        verify = exact_trajectory_verifier(calls)
        assert verify([{"name": "echo", "args": {"text": "a"}}, {"name": "file", "args": {"path": "/x", "content": "y"}}])
        assert not verify([{"name": "file", "args": {"path": "/x", "content": "y"}}, {"name": "echo", "args": {"text": "a"}}])
        assert not verify([{"name": "echo", "args": {"text": "a"}}])

    def test_exact_verifier_rejects_wrong_args(self):
        calls = (ToolCall(name="echo", args={"text": "a"}),)
        verify = exact_trajectory_verifier(calls)
        assert not verify([{"name": "echo", "args": {"text": "b"}}])


class TestGauntlet:
    def _trivial_task(self) -> ForgeTask:
        """A task any random agent solves instantly — must be rejected."""
        from trust.forge.generators import mirror_mock_tools

        tools = {t.name: t for t in mirror_mock_tools()}
        echo = tools["echo"]
        calls = (ToolCall(name="echo", args={"text": ""}),)

        def trivial_verify(trajectory):
            return any(s.get("name") == "echo" for s in trajectory)

        return ForgeTask(
            task_id="trivial-1",
            prompt="say anything",
            tools=(echo,),
            expected=calls,
            verifier=trivial_verify,
            difficulty_seed=0.1,
        )

    def _unverifiable_task(self) -> ForgeTask:
        """A task whose verifier never passes — must be rejected."""
        from trust.forge.generators import mirror_mock_tools

        tools = {t.name: t for t in mirror_mock_tools()}
        echo = tools["echo"]
        calls = (ToolCall(name="echo", args={"text": "x"}),)

        def never_verify(trajectory):
            return False

        return ForgeTask(
            task_id="unverifiable-1",
            prompt="call echo with x",
            tools=(echo,),
            expected=calls,
            verifier=never_verify,
            difficulty_seed=0.5,
        )

    def test_random_policy_floor_rejects_trivial_task(self):
        result = RandomPolicyFloor().check(self._trivial_task())
        assert not result.passed
        assert result.details["solve_rate"] > 1 / 10_000

    def test_reproducibility_rejects_unverifiable_task(self):
        result = ReproducibilityCheck().check(self._unverifiable_task())
        assert not result.passed
        assert result.checks["reference_verifies"] is False

    def test_fuzz_sweep_passes_on_clean_task(self):
        tasks = ToolUseTaskGenerator().generate(n=5)
        for t in tasks:
            result = FuzzSweep().check(t)
            assert result.passed, t.task_id

    def test_novelty_flags_duplicate_signature(self):
        tasks = ToolUseTaskGenerator().generate(n=5)
        first, second = tasks[0], tasks[1]
        result = NoveltyCheck(corpus=[first]).check(first)
        assert not result.passed  # identical to itself
        # distinct-signature task passes
        other = NoveltyCheck(corpus=[first]).check(second)
        # only flag if the signature truly matches
        same_sig = NoveltyCheck(corpus=[first])._signature(second) == NoveltyCheck(corpus=[first])._signature(first)
        if same_sig:
            assert not other.passed
        else:
            assert other.passed

    def test_full_gauntlet_accepts_clean_population(self):
        tasks = ToolUseTaskGenerator().generate(n=10)
        for t in tasks:
            result = run_gauntlet(t)
            assert result.passed, (t.task_id, result.checks)

    def test_full_gauntlet_rejects_trivial_and_unverifiable(self):
        assert not run_gauntlet(self._trivial_task()).passed
        assert not run_gauntlet(self._unverifiable_task()).passed


class TestForgeOrchestrator:
    def test_forge_gate_on_default_generator(self):
        output = forge_tasks(ToolUseTaskGenerator().generate, min_pass_rate=0.95)
        assert output.pass_rate >= 0.95
        assert output.as_dict()["n_tasks"] > 0

    def test_forge_raises_below_min_pass_rate(self):
        bad_tasks = [
            self._trivial_task(),
            self._unverifiable_task(),
        ]

        def gen():
            return bad_tasks

        with pytest.raises(ValueError, match="forge gate"):
            forge_tasks(gen, min_pass_rate=0.95)

    def test_forge_ambiguous_generator(self):
        output = forge_tasks(AmbiguousTaskGenerator().generate, min_pass_rate=0.95)
        assert output.pass_rate >= 0.95

    # -- helpers for the bad-task generator above --
    @staticmethod
    def _trivial_task() -> ForgeTask:
        from trust.forge.generators import mirror_mock_tools

        tools = {t.name: t for t in mirror_mock_tools()}
        echo = tools["echo"]
        calls = (ToolCall(name="echo", args={"text": ""}),)

        def trivial_verify(trajectory):
            return any(s.get("name") == "echo" for s in trajectory)

        return ForgeTask(
            task_id="trivial-1",
            prompt="say anything",
            tools=(echo,),
            expected=calls,
            verifier=trivial_verify,
            difficulty_seed=0.1,
        )

    @staticmethod
    def _unverifiable_task() -> ForgeTask:
        from trust.forge.generators import mirror_mock_tools

        tools = {t.name: t for t in mirror_mock_tools()}
        echo = tools["echo"]
        calls = (ToolCall(name="echo", args={"text": "x"}),)
        return ForgeTask(
            task_id="unverifiable-1",
            prompt="call echo with x",
            tools=(echo,),
            expected=calls,
            verifier=lambda trajectory: False,
            difficulty_seed=0.5,
        )
