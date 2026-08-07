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
    corpus_overlap,
    format_hint,
    format_signature,
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
        leaked = {t.task_id for t in tasks[:5]}
        probes = run_leak_probes(tasks, leaked)
        fired = [p for p in probes if p.fired]
        assert len(fired) == 5  # exactly the leaked, by unique signature
        assert all(p.probe_id in leaked for p in fired)

    def test_monitor_reports_rates(self, tasks):
        public, private = tasks[:15], tasks[15:]
        report = monitor_contamination(tasks, public=public, private=private, leaked_ids={tasks[0].task_id})
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

    def test_format_hint_withholds_no_values_only_keys(self, tasks):
        hint = format_hint(tasks[0])
        sig = format_signature(tasks[0])[0]
        for _tool, _key, value in sig:
            assert str(value) not in hint  # values must not leak into the hint itself


class TestBenchmarkRun:
    def test_end_to_end_benchmark_produces_artifacts(self, tmp_path):
        run = run_benchmark(n_tasks=30, seed=3, verbose=False)
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
