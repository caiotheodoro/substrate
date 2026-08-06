"""A-K-03 characterization-suite — the data behind the decision rule.

Runs the decision rule (A-K-02) against synthetic corpora with known-best
architectures, and validates the rule's recommendation against measured
graph-vs-flat outcomes (A-K-31). The result IS the published decision rule
with data behind it (acceptance 1).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from substrate_knowledge.m1_characterization.decision import DecisionRule
from substrate_knowledge.m1_characterization.profiler import CorpusStructuralProfiler
from substrate_knowledge.m8_benchmarks.corpora import SyntheticCorpus, build_all_corpora
from substrate_knowledge.m8_benchmarks.graph_vs_flat import GraphVsFlatResult, GraphVsFlatRunner


@dataclass
class SuiteResult:
    corpus: str
    known_best: str
    profile: dict
    rule_verdict: dict
    measured_winner: str
    rule_agrees: bool


@dataclass
class SuiteReport:
    results: list[SuiteResult] = field(default_factory=list)

    def agreement_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.rule_agrees) / len(self.results)

    def to_dict(self) -> dict:
        return {
            "results": [
                {
                    "corpus": r.corpus,
                    "known_best": r.known_best,
                    "rule_architecture": r.rule_verdict.get("architecture"),
                    "rule_refusal": r.rule_verdict.get("refusal"),
                    "measured_winner": r.measured_winner,
                    "rule_agrees": r.rule_agrees,
                    "profile": r.profile,
                }
                for r in self.results
            ],
            "agreement_rate": round(self.agreement_rate(), 3),
        }


def _measured_to_winner(runner_result: GraphVsFlatResult) -> str:
    """Map the measured winning retrieval mode to the rule's vocabulary."""
    winner = runner_result.measured_winner
    if winner == "hybrid":
        return "vector+graph"
    if winner == "graph":
        return "graph-only"
    if winner == "flat":
        return "vector"
    if winner == "tie":
        # hybrid == graph is still a graph carry: prefer the graph decision.
        if runner_result.hybrid.evidence_recall == runner_result.graph.evidence_recall:
            return "vector+graph"
        if runner_result.hybrid.evidence_recall > runner_result.flat.evidence_recall:
            return "vector+graph"
        return "vector"
    return "tie"


class CharacterizationSuite:
    def __init__(self, corpora: list[SyntheticCorpus] | None = None, budget: int = 4) -> None:
        self.corpora = corpora if corpora is not None else build_all_corpora()
        self.budget = budget
        self.profiler = CorpusStructuralProfiler()
        self.rule = DecisionRule()
        self.runner = GraphVsFlatRunner(budget=budget)

    def run(self) -> SuiteReport:
        report = SuiteReport()
        for corpus in self.corpora:
            profile = self.profiler.profile(corpus.docs)
            verdict = self.rule.decide(profile)
            runner_result = self.runner.run(corpus)
            measured = _measured_to_winner(runner_result)
            rule_arch = verdict.architecture if not verdict.refusal else None
            agrees = self._agrees(rule_arch, measured, runner_result)
            report.results.append(
                SuiteResult(
                    corpus=corpus.name,
                    known_best=corpus.known_best,
                    profile=profile.to_dict(),
                    rule_verdict=verdict.to_dict(),
                    measured_winner=measured,
                    rule_agrees=agrees,
                )
            )
        return report

    @staticmethod
    def _agrees(rule_arch: str | None, measured: str, runner_result: GraphVsFlatResult) -> bool:
        if rule_arch is None:
            return False
        if rule_arch == "vector+graph":
            # A hybrid recommendation is satisfied by a graph-only measured
            # winner with no flat deficit, or a hybrid measured winner.
            return measured in ("vector+graph", "graph-only") or (
                measured == "vector" and runner_result.hybrid.evidence_recall == runner_result.flat.evidence_recall
            )
        return measured == rule_arch