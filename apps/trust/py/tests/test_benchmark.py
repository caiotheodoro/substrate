"""Phases 3-4 — RHAE scoring, agent harness, contamination monitoring.

Gates:
- RHAE: perfect solver scores ~1.0; a 2x-inefficient solver scores ~0.25
  (power law); action budget terminates runaway agents.
- Agents: random fails (brute-force floor), perfect solves all, greedy
  somewhere between; budgets enforced.
- Contamination: leak probes fire on leaked tasks, stay silent on clean;
  structural OOD overlap between matched splits is low.
"""
from __future__ import annotations

import pytest

from trust.forge.agents import GreedySolver, PerfectSolver, RandomSolver
from trust.forge.benchmark import run_benchmark
from trust.forge.contamination import (
    ContaminationReport,
    build_reference_corpus,
    corpus_overlap,
    format_hint,
    format_signature,
    inject_leaks,
    leaked_knowledge_base,
    monitor_contamination,
    run_leak_probes,
    run_llm_leak_probes,
    structural_ood_score,
)
from trust.forge.generators import ToolUseTaskGenerator
from trust.forge.rhae import (
    action_budget,
    human_baseline_from_counts,
    linear_level_weights,
    score_environment,
    total_benchmark_score,
)


class TestRhae:
    def test_perfect_solver_scores_one(self):
        env = score_environment(
            "t1",
            human_action_counts=[[8], [10], [12]],
            agent_action_counts=[8, 10, 12],
        )
        assert env.score == pytest.approx(1.0, abs=0.02)

    def test_power_law_penalizes_inefficiency(self):
        # human 10 actions, agent 20 → (10/20)^2 = 0.25
        env = score_environment("t1", human_action_counts=[[10]], agent_action_counts=[20])
        assert env.score == pytest.approx(0.25, abs=0.02)

    def test_2x_inefficient_scores_quarter_not_half(self):
        """The power law: 2x actions → 25% credit, not 50% (the article's
        discrimination argument)."""
        s_half = score_environment("a", [[10]], [20]).score
        assert s_half == pytest.approx(0.25, abs=0.02)

    def test_uncompleted_level_scores_zero(self):
        env = score_environment("t1", human_action_counts=[[10]], agent_action_counts=[0])
        assert env.score == 0.0

    def test_level_weights_are_linear(self):
        w = linear_level_weights(5)
        assert w == pytest.approx([1 / 15, 2 / 15, 3 / 15, 4 / 15, 5 / 15])

    def test_human_baseline_upper_median_best(self):
        counts = [[12, 9], [14, 11], [20, 18]]
        assert human_baseline_from_counts(counts) == 11  # medians of bests

    def test_action_budget_is_5x(self):
        assert action_budget(10) == 50

    def test_total_is_mean_of_environments(self):
        e1 = score_environment("a", [[10]], [10])
        e2 = score_environment("b", [[20]], [20])
        assert total_benchmark_score([e1, e2]) == pytest.approx((e1.score + e2.score) / 2)


class TestAgents:
    @pytest.fixture(scope="class")
    def tasks(self):
        return ToolUseTaskGenerator().generate(n=12)

    def test_random_solver_is_floor(self, tasks):
        solver = RandomSolver(seed=1)
        solved = sum(1 for t in tasks if solver.solve(t, budget=200).solved)
        assert solved == 0  # random must not solve exact-trajectory tasks

    def test_perfect_solver_solves_all(self, tasks):
        solver = PerfectSolver()
        for t in tasks:
            run = solver.solve(t, budget=100)
            assert run.solved, t.task_id
            assert run.n_actions == len(t.expected)

    def test_greedy_is_between(self, tasks):
        """On prompt-embedded tasks greedy solves most; it's bounded below
        by random and above by perfect."""
        greedy = GreedySolver()
        g = sum(1 for t in tasks if greedy.solve(t, budget=100).solved)
        r = sum(1 for t in tasks if RandomSolver(seed=1).solve(t, budget=200).solved)
        p = sum(1 for t in tasks if PerfectSolver().solve(t, budget=100).solved)
        assert g >= r
        assert g <= p
        assert g > 0  # prompt-embedded args are solvable by following

    def test_greedy_fails_derived_arg_tasks(self):
        """Compositional difficulty: args must be derived, so prompt-
        following greedy cannot solve them."""
        from trust.forge.generators import DerivedArgTaskGenerator

        tasks = DerivedArgTaskGenerator().generate(n=10)
        g = sum(1 for t in tasks if GreedySolver().solve(t, budget=50).solved)
        assert g == 0

    def test_budget_terminates_random(self, tasks):
        solver = RandomSolver(seed=2)
        run = solver.solve(tasks[0], budget=5)
        assert run.n_actions <= 5
        assert run.terminated


class TestContamination:
    @pytest.fixture(scope="class")
    def tasks(self):
        return ToolUseTaskGenerator().generate(n=30)

    def test_leak_probes_fire_on_leaked_not_clean(self, tasks):
        """The knowledge base must be built from a source INDEPENDENT of
        `tasks` (a prior version built it from the same population being
        tested, so 'fire on leaked' was a tautological self-lookup — any
        leaked task trivially matched a KB built from itself). Here the KB
        comes from `build_reference_corpus` (a disjoint-index-range pool),
        and `inject_leaks` is what actually makes a task's signature equal
        to something in that external KB."""
        reference = build_reference_corpus(10)
        mutated, leaked_ids = inject_leaks(tasks, reference, fraction=5 / len(tasks), seed=1)
        assert len(leaked_ids) == 5
        kb = leaked_knowledge_base(reference)
        probes = run_leak_probes(mutated, kb)
        fired = [p for p in probes if p.fired]
        assert len(fired) == 5  # exactly the leaked, by unique signature
        assert {p.probe_id for p in fired} == leaked_ids

    def test_leak_probes_do_not_fire_when_kb_is_unrelated(self, tasks):
        """The other half of the tautology check: a KB that has NOTHING to
        do with this task population (no injection happened) must not
        fire on anything, by real signature mismatch — not by construction."""
        reference = build_reference_corpus(10)
        kb = leaked_knowledge_base(reference)
        probes = run_leak_probes(tasks, kb)  # tasks never mutated to match
        assert not any(p.fired for p in probes)

    def test_monitor_reports_rates(self, tasks):
        reference = build_reference_corpus(10)
        mutated, leaked_ids = inject_leaks(tasks, reference, fraction=1 / len(tasks), seed=1)
        kb = leaked_knowledge_base(reference)
        public, private = mutated[:15], mutated[15:]
        report = monitor_contamination(
            mutated, public=public, private=private, knowledge_base=kb, leaked_ids=leaked_ids
        )
        assert isinstance(report, ContaminationReport)
        d = report.as_dict()
        assert "leak_probe_fire_rate_on_leaked" in d
        assert 0.0 <= d["structural_ood_overlap"] <= 1.0

    def test_corpus_overlap_high_when_content_leaked(self, tasks):
        texts = [t.prompt for t in tasks]
        overlaps = corpus_overlap(tasks, texts)
        assert overlaps[tasks[0].task_id] == pytest.approx(1.0)  # exact copy

    def test_structural_ood_low_for_distinct_tasks(self, tasks):
        # 30 generated tasks have distinct signatures (generator spreads)
        public, private = tasks[:15], tasks[15:]
        overlap = structural_ood_score(public, private)
        assert overlap < 0.5

    def test_llm_leak_probe_fires_when_surrogate_reproduces_signature(self, tasks):
        # surrogate that "already knows" the withheld values, despite the
        # hint containing only tool names + arg keys — the Gemini-3
        # scenario: contamination, not inference from the hint.
        def cheating_surrogate(task, hint: str) -> str:
            sig = format_signature(task)[0]
            return " ".join(str(v) for _tool, _key, v in sig)

        probes = run_llm_leak_probes(tasks[:5], complete_fn=cheating_surrogate)
        assert all(p.fired for p in probes)
        assert len(probes) == 5

    def test_llm_leak_probe_silent_when_surrogate_cannot_reproduce(self, tasks):
        def honest_surrogate(task, hint: str) -> str:
            return "I don't know the exact values."

        probes = run_llm_leak_probes(tasks[:5], complete_fn=honest_surrogate)
        assert not any(p.fired for p in probes)

    def test_llm_leak_probe_does_not_fire_on_substring_coincidence(self):
        """`str(value) in completion` fires on ANY substring match — a
        completion containing "13" would trivially "reproduce" a value of
        3 (str(3) == "3", and "3" is a substring of "13"). Small int-typed
        args make this a real false-positive risk: several mock tools
        (sum, delay) use plain integers. A single-call, single-int-arg
        task isolates the bug precisely — a surrogate that only mentions
        the value embedded inside a larger, unrelated number must not be
        flagged as having reproduced it."""
        from trust.forge.generators import mirror_mock_tools
        from trust.forge.task import ForgeTask, ToolCall

        by_name = {t.name: t for t in mirror_mock_tools()}
        task = ForgeTask(
            task_id="int-arg-1",
            prompt="delay 3ms",
            tools=(by_name["delay"],),
            expected=(ToolCall(name="delay", args={"ms": 3}),),
            verifier=lambda trajectory: True,
            difficulty_seed=0.3,
        )

        def near_miss_surrogate(task, hint: str) -> str:
            return "somewhere around 13 or 39, hard to say exactly"

        probes = run_llm_leak_probes([task], complete_fn=near_miss_surrogate)
        assert not probes[0].fired, probes[0].detail

        def exact_surrogate(task, hint: str) -> str:
            return "it's 3 milliseconds"

        probes2 = run_llm_leak_probes([task], complete_fn=exact_surrogate)
        assert probes2[0].fired, probes2[0].detail

    def test_llm_leak_probe_logs_the_completion_not_just_fired(self, tasks):
        """A total network outage and a genuinely honest 'I don't know'
        both produce fired=False — previously indistinguishable in the
        artifact (only hint + fired/not were recorded). The completion
        itself must be visible so a real result can be told apart from a
        masked failure on inspection."""

        def surrogate(task, hint: str) -> str:
            return "the model actually said this exact sentence"

        probes = run_llm_leak_probes(tasks[:1], complete_fn=surrogate)
        assert "the model actually said this exact sentence" in probes[0].detail

    def test_format_hint_withholds_no_values_only_keys(self, tasks):
        hint = format_hint(tasks[0])
        sig = format_signature(tasks[0])[0]
        for _tool, _key, value in sig:
            assert str(value) not in hint  # values must not leak into the hint itself


class TestBenchmarkRun:
    def test_end_to_end_benchmark_produces_artifacts(self, tmp_path):
        # n_tasks=120: split predictability needs enough post-calibration
        # tasks per difficulty bin for a stable correlation (S2's own
        # sample-size lesson) — 30 tasks shrinks to ~33 calibrated survivors
        # after the 2-of-10 bar is actually enforced, too few for a
        # reliable >=0.8 correlation on the synthetic-system check below.
        run = run_benchmark(n_tasks=120, seed=3, verbose=False)
        assert run.metadata["gauntlet_pass_rate"] >= 0.95
        assert run.scores["perfect"]["total"] > 0.9
        assert run.scores["random"]["total"] < 0.1
        assert 0.0 < run.scores["greedy"]["total"] < run.scores["perfect"]["total"]
        # split predictability passed
        assert run.metadata["split_predictability"]["passed"]
        # contamination monitor present
        assert "leak_probe_fire_rate_on_leaked" in run.contamination
        path = run.write(tmp_path)
        assert path.exists()

    def test_only_calibrated_tasks_are_scored(self, tmp_path):
        """The 2-of-10 bar is a rejection gate, not a diagnostic: a task
        nobody reliably solves twice must not reach difficulty fitting,
        stratification, or scoring. `calibration` in the artifact still
        reports every gauntlet survivor (rejects included, for
        transparency); `tasks`/`difficulty`/`scores` must not."""
        run = run_benchmark(n_tasks=40, seed=5, verbose=False)
        n_gauntlet = run.metadata["n_gauntlet_survivors"]
        n_calibrated = run.metadata["n_calibrated"]
        assert n_calibrated <= n_gauntlet
        # every task actually carried through to scoring passed calibration
        assert len(run.tasks) == n_calibrated
        assert len(run.difficulty) == n_calibrated
        assert set(run.difficulty) == {t.task_id for t in run.tasks}
        for solver_runs in run.solver_runs.values():
            assert len(solver_runs) == n_calibrated
        # every scored task's own calibration record says solved
        for t in run.tasks:
            assert run.calibration[t.task_id]["solved"]
        # but rejected gauntlet survivors (if any) still have a visible
        # calibration record — rejection isn't silent
        assert len(run.calibration) == n_gauntlet

    def test_rhae_efficiency_varies_across_solved_tasks(self):
        """The whole point of RHAE is a per-task efficiency SIGNAL, not a
        relabeled solve rate. Before the fix, every solved task scored
        exactly the same (agent_actions always == len(expected), human
        baseline unrelated to task length, ratio always saturating the 1.15
        cap) — RHAE total was arithmetically identical to solve rate for
        every solver. After grounding the human baseline in task length and
        making the verifier suffix-tolerant (so a struggling-but-eventually-
        correct agent's action count can exceed len(expected)), per-level
        efficiency must show real spread, not a single repeated value."""
        run = run_benchmark(n_tasks=60, seed=9, verbose=False)
        perfect_scores = run.scores["perfect"]["environments"]
        efficiencies = [
            lvl["efficiency"]
            for env in perfect_scores
            for lvl in env["levels"]
            if lvl["agent_actions"] > 0  # solved levels only
        ]
        assert len(efficiencies) > 10, "need enough solved levels to see spread"
        distinct = {round(e, 3) for e in efficiencies}
        assert len(distinct) > 1, (
            f"every solved level scored the exact same efficiency ({distinct}) — "
            "RHAE is still measuring nothing but solve rate"
        )


class TestLlmSolverBridge:
    def test_llm_solver_solves_via_openai_compat_endpoint(self):
        """The LLM bridge speaks OpenAI-compatible chat completions. A fake
        server acts as a perfect model (emits the expected call) and the
        solver must solve the task through it."""
        import json
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        from trust.forge.agents import LlmSolver
        from trust.forge.generators import ToolUseTaskGenerator

        tasks = ToolUseTaskGenerator().generate(n=3)
        expected = tasks[0].expected
        expected_payloads = [json.dumps({"name": c.name, "args": c.args}) for c in expected]
        call_count = {"n": 0}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                body = json.loads(self.rfile.read(length))
                assert body["model"] == "mock-model"
                assert body["messages"][0]["role"] == "user"
                idx = min(call_count["n"], len(expected_payloads) - 1)
                call_count["n"] += 1
                resp = {"choices": [{"message": {"content": expected_payloads[idx]}}]}
                data = json.dumps(resp).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            solver = LlmSolver(base_url=f"http://127.0.0.1:{port}/v1", model="mock-model")
            run = solver.solve(tasks[0], budget=5)
            assert run.solved, run.trajectory
            assert run.n_actions == len(expected)
        finally:
            server.shutdown()

    def test_llm_solver_fails_cleanly_when_endpoint_down(self):
        from trust.forge.agents import LlmSolver
        from trust.forge.generators import ToolUseTaskGenerator

        tasks = ToolUseTaskGenerator().generate(n=2)
        solver = LlmSolver(base_url="http://127.0.0.1:1/v1", model="none")
        run = solver.solve(tasks[0], budget=3)
        assert not run.solved
        assert run.n_actions == 0  # clean failure, no crash

    def test_llm_solver_recovers_from_a_hallucinated_tool_call(self):
        """A single wrong/hallucinated tool call must cost one wasted
        action, not end the whole episode — a prior version treated any
        StopIteration (tool name not found) or JSON parse error the same
        as a dead endpoint (break immediately), so a real model that
        second-guesses itself once and then gets it right was scored as a
        total failure. With the suffix-tolerant verifier (see
        generators._exact_verifier), a trajectory that pads a wrong call
        in front of the correct sequence should still verify — this test
        checks the solver actually KEEPS GOING to give it that chance."""
        import json
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        from trust.forge.agents import LlmSolver
        from trust.forge.generators import ToolUseTaskGenerator

        tasks = ToolUseTaskGenerator().generate(n=3)
        expected = tasks[0].expected
        expected_payloads = [json.dumps({"name": c.name, "args": c.args}) for c in expected]
        # first call hallucinates a tool that doesn't exist on this task
        responses = [json.dumps({"name": "definitely-not-a-real-tool", "args": {}})] + expected_payloads
        call_count = {"n": 0}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                json.loads(self.rfile.read(length))
                idx = min(call_count["n"], len(responses) - 1)
                call_count["n"] += 1
                resp = {"choices": [{"message": {"content": responses[idx]}}]}
                data = json.dumps(resp).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            solver = LlmSolver(base_url=f"http://127.0.0.1:{port}/v1", model="mock-model")
            run = solver.solve(tasks[0], budget=len(expected) + 3)
            assert run.solved, run.trajectory
            # one wasted action (the hallucinated call) plus the correct
            # sequence -- strictly more actions than the minimal path
            assert run.n_actions == len(expected) + 1
        finally:
            server.shutdown()
